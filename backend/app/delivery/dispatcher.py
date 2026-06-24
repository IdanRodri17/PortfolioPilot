"""
Delivery dispatcher — run the report graph once and deliver it (V7).

This is the service layer the V7 design calls the "dispatcher". It lives at the
graph's boundary, exactly like api/generate.py: the graph itself knows nothing
about delivery (graph purity, pattern #7). deliver_for_user reuses the SAME
compiled, checkpointer-bound graph singleton the API uses — the reuse the
generate.py docstring anticipated for the scheduler. No graph changes in V7.

Run-once, render-down (design decision #3): ONE graph run produces ONE
FinalReport, rendered to each enabled channel. We never run the graph twice
because two channels are checked.

Read-only memory for unattended runs (design decision #2): the V6 graph pauses
at human_review to let a human approve proposed memories. A scheduled/triggered
run has no human, so we resume immediately with NO approvals — the report is
delivered and persisted, but the run writes nothing to long-term memory and the
checkpoint reaches END cleanly (no orphaned paused threads). Scheduled reports
READ memory (memory_loader still personalizes) but never WRITE it.

DB access mirrors generate.py: read everything the run + sends need into plain
values and release the session BEFORE the async graph work — no ORM object or
session is held across an await (pattern #7). The archive and the last_sent_at
stamp each use their own short-lived session.

Versioning:
    V7: this file (V7c).
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo


from langgraph.types import Command

import app.graph.builder as graph_builder
from app.api.generate import _persist_report
from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import User, DeliveryPreference
from app.delivery.renderers import render_email_html, render_telegram_brief
from app.tools.email_sender import send_email
from app.tools.telegram_sender import send_telegram_message

logger = logging.getLogger(__name__)

_EMAIL_SUBJECT = "Your PortfolioPilot report"


class DeliveryError(Exception):
    """Raised when a delivery cannot be PRODUCED (no portfolio, no report).

    Distinct from a per-channel send failure, which is best-effort: those are
    caught, logged, and reported in the result, never raised.
    """


async def deliver_for_user(user_id: str) -> dict:
    """Produce one report for the user and deliver it to each enabled channel.

    Returns {report_id, channels: {telegram?: "sent"|"failed: ...", email?: ...}}
    or {skipped: ...} when there is no enabled preference. Raises DeliveryError
    if the report itself can't be produced.
    """
    # 1. Read everything the run + sends need, then release the session — we
    #    must not hold an ORM session across the async graph run (pattern #7).
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or user.portfolio is None:
            raise DeliveryError(f"No portfolio found for user_id '{user_id}'.")
        pref = user.delivery_preference
        if pref is None or not pref.enabled:
            return {"skipped": "no enabled delivery preference", "channels": {}}
        ctx = {
            "portfolio": dict(user.portfolio.assets),
            "cost_basis": dict(user.portfolio.cost_basis or {}),
            "risk_profile": user.risk_profile,
            "email": user.email,
            "chat_id": user.telegram_chat_id,
            "deliver_email": bool(pref.deliver_email),
            "deliver_telegram": bool(pref.deliver_telegram),
        }
    finally:
        db.close()

    # 2. Run the graph once. It pauses at human_review (if any memories were
    #    proposed); we resume with NO approvals = read-only memory for an
    #    unattended run, and the checkpoint reaches END cleanly.
    report_id = str(uuid4())
    config = {"configurable": {"thread_id": report_id}}
    initial_state = {
        "user_id": user_id,
        "portfolio": ctx["portfolio"],
        "cost_basis": ctx["cost_basis"],
        "risk_profile": ctx["risk_profile"],
    }
    graph = graph_builder.graph  # dynamic read: the checkpointer-bound singleton

    result = await graph.ainvoke(initial_state, config=config) or {}
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}

    # Prefer the live ainvoke return; fall back to checkpoint state (robust
    # across LangGraph version quirks in what ainvoke returns on interrupt).
    final_report = result.get("final_report") or values.get("final_report")
    guardrail_passed = result.get("guardrail_passed")
    if guardrail_passed is None:
        guardrail_passed = values.get("guardrail_passed")
    if final_report is None:
        raise DeliveryError("Graph finished without a final_report.")

    if snapshot.next and "human_review" in snapshot.next:
        await graph.ainvoke(Command(resume={"approved_indices": []}), config=config)

    payload = (
        final_report.model_dump(mode="json")
        if hasattr(final_report, "model_dump")
        else final_report
    )

    # 3. Archive so the scheduled report shows up in /history too (reuse #37).
    try:
        _persist_report(report_id, user_id, payload, guardrail_passed)
    except Exception:  # noqa: BLE001 — a failed archive must never sink delivery
        logger.exception("deliver_for_user: archive failed for %s", report_id)

    # 4. Render down + send, best-effort per channel (a failed channel must not
    #    block the other). The sync senders run in a worker thread so a blocking
    #    HTTPS POST never sits on the event loop.
    base_url = get_settings().public_app_base_url
    channels: dict = {}

    if ctx["deliver_telegram"] and ctx["chat_id"]:
        try:
            await asyncio.to_thread(
                send_telegram_message,
                ctx["chat_id"],
                render_telegram_brief(payload, base_url),
            )
            channels["telegram"] = "sent"
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning(
                "deliver_for_user: telegram failed for %s — %s", user_id, exc
            )
            channels["telegram"] = f"failed: {exc}"

    if ctx["deliver_email"] and ctx["email"]:
        try:
            await asyncio.to_thread(
                send_email,
                ctx["email"],
                _EMAIL_SUBJECT,
                render_email_html(payload, base_url),
            )
            channels["email"] = "sent"
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("deliver_for_user: email failed for %s — %s", user_id, exc)
            channels["email"] = f"failed: {exc}"

    # 5. Stamp last_sent_at only if something actually went out — a total
    #    failure then retries next tick instead of silently marking it sent.
    if any(v == "sent" for v in channels.values()):
        db = SessionLocal()
        try:
            user = db.get(User, user_id)
            if user and user.delivery_preference:
                user.delivery_preference.last_sent_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    return {"report_id": report_id, "channels": channels}


def _is_due(pref: DeliveryPreference, now: datetime) -> bool:
    """Is a send due for this preference at `now` (an aware UTC datetime)?

    The rule: the current period's scheduled LOCAL time has arrived, and we
    haven't already sent for this period. Computed in the user's IANA zone, so
    '08:00 local' is correct across DST — we resolve the zone per-date and never
    freeze a UTC offset. A bad zone is skipped rather than allowed to crash the
    whole batch.
    """
    if not pref.enabled:
        return False
    try:
        tz = ZoneInfo(pref.timezone)
    except Exception:  # noqa: BLE001 — a bad zone disables this user, not the batch
        logger.warning(
            "_is_due: bad timezone %r; skipping %s", pref.timezone, pref.user_id
        )
        return False

    now_local = now.astimezone(tz)
    st = pref.send_time_local
    scheduled = now_local.replace(
        hour=st.hour, minute=st.minute, second=0, microsecond=0
    )
    if now_local < scheduled:
        return False  # today's send time hasn't arrived yet

    last = pref.last_sent_at  # aware UTC, or None

    if pref.cadence == "weekly":
        if pref.weekday is None or now_local.weekday() != pref.weekday:
            return False
        return last is None or last < scheduled

    if pref.cadence == "every_n_days":
        n = pref.interval_days or 1
        if last is None:
            return True
        return (now_local.date() - last.astimezone(tz).date()).days >= n

    # daily (default)
    return last is None or last < scheduled


async def dispatch_due() -> dict:
    """Deliver to every enabled preference that is due now.

    Best-effort across users: one user's failure is logged and the batch
    continues. Idempotent within a period because deliver_for_user stamps
    last_sent_at, which _is_due reads — so a ~10-minute trigger never double-sends.
    """
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        prefs = (
            db.query(DeliveryPreference)
            .filter(DeliveryPreference.enabled.is_(True))
            .all()
        )
        due_ids = [p.user_id for p in prefs if _is_due(p, now)]
        total = len(prefs)
    finally:
        db.close()

    logger.info("dispatch_due: %d enabled, %d due", total, len(due_ids))
    results: dict = {}
    for uid in due_ids:
        try:
            results[uid] = await deliver_for_user(uid)
        except Exception as exc:  # noqa: BLE001 — one user can't sink the batch
            logger.exception("dispatch_due: delivery failed for %s", uid)
            results[uid] = {"error": str(exc)}

    return {"checked_at": now.isoformat(), "due": len(due_ids), "results": results}

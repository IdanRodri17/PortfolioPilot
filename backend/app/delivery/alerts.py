"""Threshold alerts — condition-based pushes, evaluated on the scheduler tick (V18).

The V7 dispatcher delivers a *scheduled* digest (run the graph, render, send on a
cadence). Alerts are the complement: *condition-based* pushes that fire the moment
a holding moves, the whole portfolio swings, or one position grows too large.

Two deliberate design choices keep this cheap enough to run every tick:

  1. NO graph run. Alerts are a pure market-data check — fetch each holding's
     price + 24h change (the same tools data_ingestion uses) and compare to the
     user's thresholds. No LLM, no synthesizer, no checkpointer. Running the full
     report every ~10 minutes per user would be slow and expensive; a price
     lookup is neither.

  2. Per-rule cooldown dedupe. A fired rule stamps its key into
     DeliveryPreference.alert_state; it won't re-fire until alert_cooldown_hours
     pass. So a frequent tick (or a stock hovering just past the line) never
     spams the same condition — mirroring how the dispatcher's last_sent_at keeps
     the digest idempotent within a period.

Everything is opt-in: alerts_enabled is the master switch and each rule is live
only when its threshold column is non-NULL. The session discipline matches the
dispatcher (pattern #7): read everything into plain values and release the
session BEFORE the blocking fetch / sends, then reopen a short-lived session to
stamp cooldowns.

Versioning:
    V18: this file.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import DeliveryPreference, User
from app.delivery.renderers import render_alert_email, render_alert_telegram
from app.tools.email_sender import send_email
from app.tools.stock_data import (
    StockDataError,
    fetch_crypto_data,
    fetch_stock_data,
    is_crypto,
)
from app.tools.telegram_sender import send_telegram_message

logger = logging.getLogger(__name__)

_ALERT_SUBJECT = "PortfolioPilot alert"
_DEFAULT_COOLDOWN_HOURS = 12


# ─── market data (cheap, deterministic — no LLM) ──────────────────────────────


def _fetch_market(holdings: dict[str, float]) -> dict[str, dict]:
    """{symbol: {"price": USD, "change_24h_percent": float}} for each holding.

    Routes crypto -> CoinGecko and everything else (incl. TASE ".TA") -> yfinance,
    exactly like data_ingestion; both return the same USD-normalized shape. A
    symbol whose fetch fails is skipped, not fatal — partial data still yields
    useful alerts. Sync by design; the caller runs it in a worker thread.
    """
    out: dict[str, dict] = {}
    for symbol in holdings:
        try:
            out[symbol] = (
                fetch_crypto_data(symbol) if is_crypto(symbol) else fetch_stock_data(symbol)
            )
        except StockDataError as exc:
            logger.warning("alerts: skipping %s — %s", symbol, exc)
    return out


# ─── rule evaluation (pure — trivially unit-testable) ─────────────────────────


def _evaluate_rules(
    *,
    holdings: dict[str, float],
    market: dict[str, dict],
    price_move_pct: float | None,
    portfolio_move_pct: float | None,
    concentration_pct: float | None,
) -> list[dict]:
    """Return the list of triggered alerts as [{"key", "message"}].

    `key` is the dedupe identity (one per symbol per rule, or "portfolio:move");
    `message` is the human line. Pure: no I/O, no clock — same inputs, same
    output — so the dispatcher path and the preview endpoint share one source of
    truth and a literal portfolio tests it.
    """
    alerts: list[dict] = []

    # Value each priced holding in USD; the unpriced are simply absent.
    values = {
        sym: holdings[sym] * market[sym]["price"]
        for sym in holdings
        if sym in market
    }
    total = sum(values.values())

    def arrow(x: float) -> str:
        return "▲" if x >= 0 else "▼"

    # 1. Per-holding 24h move.
    if price_move_pct:
        for sym in sorted(values):
            change = float(market[sym].get("change_24h_percent", 0.0) or 0.0)
            if abs(change) >= price_move_pct:
                alerts.append(
                    {
                        "key": f"price:{sym}",
                        "message": (
                            f"{sym}: {arrow(change)} {change:+.2f}% in the last 24h "
                            f"(now ${values[sym]:,.0f})."
                        ),
                    }
                )

    # 2. Whole-portfolio 24h move — value-weighted, like the report's headline.
    if portfolio_move_pct and total > 0:
        weighted = (
            sum(
                values[sym] * float(market[sym].get("change_24h_percent", 0.0) or 0.0)
                for sym in values
            )
            / total
        )
        if abs(weighted) >= portfolio_move_pct:
            alerts.append(
                {
                    "key": "portfolio:move",
                    "message": (
                        f"Your portfolio is {arrow(weighted)} {weighted:+.2f}% in the "
                        f"last 24h (now ${total:,.0f})."
                    ),
                }
            )

    # 3. Single-holding concentration (reuses the V11 weight idea).
    if concentration_pct and total > 0:
        for sym in sorted(values):
            pct = values[sym] / total * 100
            if pct >= concentration_pct:
                alerts.append(
                    {
                        "key": f"conc:{sym}",
                        "message": (
                            f"{sym} is {pct:.1f}% of your portfolio — above your "
                            f"{concentration_pct:.0f}% limit."
                        ),
                    }
                )

    return alerts


# ─── cooldown ─────────────────────────────────────────────────────────────────


def _on_cooldown(state: dict, key: str, now: datetime, cooldown_hours: int) -> bool:
    """Has `key` fired within the last `cooldown_hours`? A malformed/absent stamp
    means 'not on cooldown' (fire), never a crash."""
    raw = state.get(key)
    if not raw:
        return False
    try:
        last = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return False
    return now - last < timedelta(hours=cooldown_hours)


# ─── per-user evaluation ──────────────────────────────────────────────────────


async def evaluate_for_user(user_id: str, *, dry_run: bool = False) -> dict:
    """Evaluate one user's alert rules and (unless dry_run) deliver the fresh ones.

    dry_run powers the settings "Preview alerts" button: it evaluates the rules
    and returns what WOULD fire right now, ignoring both the master switch and
    the cooldown — and never sends or mutates state. The live path honors both.
    """
    # 1. Snapshot everything the check + sends need, then release the session.
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or user.portfolio is None:
            return {"skipped": "no portfolio", "alerts": []}
        pref = user.delivery_preference
        if pref is None:
            return {"skipped": "no delivery preference", "alerts": []}
        thresholds = {
            "price_move_pct": pref.alert_price_move_pct,
            "portfolio_move_pct": pref.alert_portfolio_move_pct,
            "concentration_pct": pref.alert_concentration_pct,
        }
        ctx = {
            "holdings": dict(user.portfolio.assets),
            "alerts_enabled": bool(pref.alerts_enabled),
            "cooldown_hours": pref.alert_cooldown_hours or _DEFAULT_COOLDOWN_HOURS,
            "state": dict(pref.alert_state or {}),
            "email": user.email,
            "chat_id": user.telegram_chat_id,
            "deliver_email": bool(pref.deliver_email),
            "deliver_telegram": bool(pref.deliver_telegram),
        }
    finally:
        db.close()

    if not dry_run and not ctx["alerts_enabled"]:
        return {"skipped": "alerts disabled", "alerts": []}
    if not any(thresholds.values()):
        return {"skipped": "no alert rules set", "alerts": []}

    # 2. Fetch prices off the event loop, then evaluate the (pure) rules.
    market = await asyncio.to_thread(_fetch_market, ctx["holdings"])
    triggered = _evaluate_rules(
        holdings=ctx["holdings"], market=market, **thresholds
    )

    if dry_run:
        return {
            "alerts": [t["message"] for t in triggered],
            "evaluated_symbols": sorted(market.keys()),
            "alerts_enabled": ctx["alerts_enabled"],
        }

    # 3. Cooldown filter — only keys not fired within the window go out.
    now = datetime.now(timezone.utc)
    fresh = [
        t
        for t in triggered
        if not _on_cooldown(ctx["state"], t["key"], now, ctx["cooldown_hours"])
    ]
    if not fresh:
        return {"alerts": [], "sent": {}, "suppressed": len(triggered)}

    messages = [t["message"] for t in fresh]
    base_url = get_settings().public_app_base_url
    channels: dict = {}

    if ctx["deliver_telegram"] and ctx["chat_id"]:
        try:
            await asyncio.to_thread(
                send_telegram_message,
                ctx["chat_id"],
                render_alert_telegram(messages, base_url),
            )
            channels["telegram"] = "sent"
        except Exception as exc:  # noqa: BLE001 — best-effort per channel
            logger.warning("alerts: telegram failed for %s — %s", user_id, exc)
            channels["telegram"] = f"failed: {exc}"

    if ctx["deliver_email"] and ctx["email"]:
        try:
            await asyncio.to_thread(
                send_email,
                ctx["email"],
                _ALERT_SUBJECT,
                render_alert_email(messages, base_url),
            )
            channels["email"] = "sent"
        except Exception as exc:  # noqa: BLE001 — best-effort per channel
            logger.warning("alerts: email failed for %s — %s", user_id, exc)
            channels["email"] = f"failed: {exc}"

    # 4. Stamp cooldown ONLY for keys that actually went out — a total send
    #    failure retries next tick rather than silently muting the condition.
    if any(v == "sent" for v in channels.values()):
        db = SessionLocal()
        try:
            user = db.get(User, user_id)
            if user and user.delivery_preference:
                state = dict(user.delivery_preference.alert_state or {})
                for t in fresh:
                    state[t["key"]] = now.isoformat()
                # Reassign (not in-place mutate) so SQLAlchemy flags the JSONB dirty.
                user.delivery_preference.alert_state = state
                db.commit()
        finally:
            db.close()

    return {"alerts": messages, "sent": channels}


async def evaluate_alerts_due() -> dict:
    """Scheduler entrypoint: evaluate every user who has alerts enabled.

    Best-effort across users — one user's failure is logged and the batch
    continues — exactly like dispatch_due.
    """
    db = SessionLocal()
    try:
        user_ids = [
            p.user_id
            for p in db.query(DeliveryPreference)
            .filter(DeliveryPreference.alerts_enabled.is_(True))
            .all()
        ]
    finally:
        db.close()

    logger.info("evaluate_alerts_due: %d users with alerts enabled", len(user_ids))
    results: dict = {}
    for uid in user_ids:
        try:
            results[uid] = await evaluate_for_user(uid, dry_run=False)
        except Exception as exc:  # noqa: BLE001 — one user can't sink the batch
            logger.exception("evaluate_alerts_due: failed for %s", uid)
            results[uid] = {"error": str(exc)}
    return {"checked": len(user_ids), "results": results}

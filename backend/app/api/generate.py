"""
Routes for report generation.

V1: hardcoded portfolio {"AAPL": 10}, JSON return.
V2: portfolio fetched from DB by user_id. Graph signature unchanged.
V3: same handler, graph fans out internally to parallel agents.
V4: SSE streaming replaces the JSON return. The handler still does the
    DB lookup synchronously, then hands a self-contained event generator
    to StreamingResponse. graph.astream_events() drives the stream.
V5: the handler mints a report_id (uuid4) and the generator archives the
    finished FinalReport to the reports table via its OWN short-lived
    session, then includes report_id in the report_complete payload.
V6: this endpoint may emit human_input_required mid-stream; the client
    resumes against POST /api/resume-graph. report_id becomes the
    checkpointer thread_id.

Architectural note — why DB lookup lives here, not in a node:
    The graph is a pure pipeline: portfolio_dict -> FinalReport. It does
    not know portfolios live in Postgres. This boundary is load-bearing
    for V8: the daily-digest scheduler will fetch every user's portfolio,
    loop, and pass each assets dict into the same graph. If DB access
    leaked into data_ingestion, the scheduler would have to re-fetch
    (waste) or special-case the node (entangle). Same reason makes the
    graph trivially testable — no DB fixtures, just a dict.

Architectural note — two kinds of DB access in this file:
    1. The request-scoped get_db session does the portfolio LOOKUP, before
       streaming starts. We never hold it across the stream.
    2. The report ARCHIVE write (V5) happens inside the generator, but with
       its OWN short-lived SessionLocal opened and closed within a single
       await-free window — not the request session. The generator stays
       free of the request session; it just borrows a fresh one for one
       insert. No ORM objects cross the streaming window (pattern #7).

Why report persistence is best-effort:
    The report is already produced and about to be streamed. If archiving
    it fails (DB blip), we log and still emit report_complete — filing a
    copy must never deny the user a result they already have (pattern #22).

Why we don't emit `token` events: the synthesizer uses
    .with_structured_output(FinalReport), so the model emits one JSON/
    tool-call object; streaming its tokens yields partial JSON, not prose.
    The streaming that carries the demo is the burst of `status` events.

Why sentiment start/end are paired by run_id:
    Each parallel sentiment_agent Send branch is one runnable invocation,
    and astream_events gives that invocation a single run_id shared by its
    on_chain_start and on_chain_end. The start event exposes the branch's
    symbol via data.input; the end event does not. So we stash
    run_id -> symbol on start and look it up on end.
"""

import json
import logging
from datetime import date
from uuid import uuid4

from langgraph.types import Command
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import DEMO_USER_ID, require_user, verify_token
from app.db.base import get_db, SessionLocal
from app.db.models import User, Report
from app.schemas.report import AdviceReview, GradedCall, ReportDiff, SentimentFlip
from app.tools.stock_data import price_on
import app.graph.builder as graph_builder

logger = logging.getLogger(__name__)

router = APIRouter()


# The graph node names we surface to the client as `status` events.
# astream_events emits on_chain_start/end for many runnables — the
# top-level graph, conditional-edge functions, prompts, chat models,
# parsers. Filtering on this set keeps the status feed to the nodes the
# user cares about. memory_loader (V5 step 3b) and memory_extractor (V5
# step 5b) were added here; the V6 guardrail/human_review/memory_saver
# nodes will join then.
_STATUS_NODES = {
    "memory_loader",
    "data_ingestion",
    "sentiment_agent",
    "risk_agent",
    "macro_context_agent",
    "synthesizer",
    "guardrail",
    "memory_extractor",
    "memory_saver",
}


def get_graph():
    """Provider for the compiled graph singleton.

    Reads builder.graph dynamically (not a value bound at import) so it returns
    the checkpointer-bound graph the lifespan recompiles. Tests still override
    via app.dependency_overrides[get_graph].
    """
    return graph_builder.graph


def _format_sse(event_type: str, data: dict) -> str:
    """Serialize one SSE message: an `event:` line, a `data:` JSON line,
    terminated by a blank line per the SSE spec."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _persist_report(
    report_id: str, user_id: str, payload: dict, guardrail_passed=None
) -> None:
    confidence = payload.get("confidence", 0.0)
    flag = "high" if confidence >= 0.6 else "low"
    if guardrail_passed is False:
        flag = "low"
    db = SessionLocal()
    try:
        db.add(
            Report(
                id=report_id, user_id=user_id, raw_result=payload, confidence_flag=flag
            )
        )
        db.commit()
    finally:
        db.close()


def _compute_report_diff(prev: dict | None, curr: dict) -> dict:
    """Diff the new report against the user's previous one (V12b).

    Deterministic, no LLM. Risk violations aren't persisted on the report, so
    the actionable diff is over rebalancing_recommendations (keyed
    "action asset") — the surfaced form of those violations. Returns a
    ReportDiff as a JSON-ready dict.
    """
    if not prev:
        return ReportDiff(first_report=True).model_dump(mode="json")

    prev_total = (prev.get("portfolio_valuation") or {}).get("total_usd")
    curr_total = (curr.get("portfolio_valuation") or {}).get("total_usd")
    delta = None
    if prev_total and curr_total is not None:  # prev_total truthy => nonzero
        delta = round((curr_total - prev_total) / prev_total * 100, 2)

    prev_sent = {i["asset"]: i["sentiment"] for i in prev.get("market_insights", [])}
    curr_sent = {i["asset"]: i["sentiment"] for i in curr.get("market_insights", [])}
    flips = [
        SentimentFlip(asset=asset, previous=prev_sent[asset], current=sentiment)
        for asset, sentiment in curr_sent.items()
        if asset in prev_sent and prev_sent[asset] != sentiment
    ]

    def _rec_keys(report: dict) -> set[str]:
        return {
            f"{r['action']} {r['asset']}"
            for r in report.get("rebalancing_recommendations", [])
        }

    prev_recs = _rec_keys(prev)
    curr_recs = _rec_keys(curr)

    return ReportDiff(
        first_report=False,
        valuation_delta_pct=delta,
        sentiment_flips=flips,
        recommendations_new=sorted(curr_recs - prev_recs),
        recommendations_resolved=sorted(prev_recs - curr_recs),
    ).model_dump(mode="json")


# A directional call needs a real move to be judged a win or a miss; below this
# the move is "too close to call" → neutral. This also covers same-day grading
# (prior report and now share a close → 0.00% move), which must not read as a
# miss.
_FLAT_MOVE_PCT = 0.5
# A hold is rewarded for staying within this band; beyond it the hold is neutral.
_HOLD_FLAT_PCT = 5.0


def _grade_call(action: str, pct_move: float) -> str:
    """Grade one prior call from the asset's % move since it was made."""
    if action == "hold":
        # Rewarded for staying ~flat; a large move is neutral, not a miss.
        return "good" if abs(pct_move) < _HOLD_FLAT_PCT else "neutral"
    if abs(pct_move) < _FLAT_MOVE_PCT:
        return "neutral"  # too small a move to call directionally
    if action == "reduce":
        return "good" if pct_move < 0 else "poor"  # reduce + fell = good call
    return "good" if pct_move > 0 else "poor"  # increase + rose = good call


def _compute_advice_review(prev: dict | None, prev_at) -> dict:
    """Grade the previous report's recommendations against actual price moves.

    Deterministic (no LLM): for each prior rec, compare the asset's close on the
    prior report's date with its current close (both via price_on, which falls
    back to the nearest prior trading day and never raises — an unretrievable
    price -> "insufficient_data"). One-step look-back only. Returns an
    AdviceReview as a JSON-ready dict.
    """
    if not prev or prev_at is None:
        return AdviceReview(
            summary="No prior recommendations to grade yet."
        ).model_dump(mode="json")

    prev_date = prev_at.date()
    recs = prev.get("rebalancing_recommendations", [])
    if not recs:
        return AdviceReview(
            recommended_at=prev_date.isoformat(),
            summary="The previous report made no recommendations to grade.",
        ).model_dump(mode="json")

    today = date.today()
    calls: list[GradedCall] = []
    tally = {"good": 0, "poor": 0, "neutral": 0, "insufficient_data": 0}
    for rec in recs:
        asset, action = rec["asset"], rec["action"]
        historical = price_on(asset, prev_date)
        current = price_on(asset, today)
        if historical is None or current is None or historical == 0:
            grade, pct_move = "insufficient_data", None
        else:
            pct_move = round((current - historical) / historical * 100, 2)
            grade = _grade_call(action, pct_move)
        tally[grade] += 1
        calls.append(
            GradedCall(
                asset=asset,
                action=action,
                recommended_at=prev_date.isoformat(),
                pct_move_since=pct_move,
                grade=grade,
            )
        )

    labels = (
        ("good", "good"),
        ("poor", "poor"),
        ("neutral", "neutral"),
        ("insufficient_data", "ungradeable"),
    )
    parts = [f"{tally[key]} {label}" for key, label in labels if tally[key]]
    return AdviceReview(
        recommended_at=prev_date.isoformat(),
        calls=calls,
        summary=" · ".join(parts) if parts else "no gradeable calls",
    ).model_dump(mode="json")


async def _report_event_stream(
    graph,
    initial_state: dict,
    report_id: str,
    prev_report: dict | None,
    prev_generated_at=None,
):
    """Map the astream_events firehose to SSE events.

    Yields status events per node, then report_complete (FinalReport +
    report_id), then report_diff (V12b: what changed vs prev_report) and
    advice_review (V13: how the prior report's calls aged). If the graph paused
    at human_review's interrupt (V6), also yields human_input_required so the
    client can open the memory-approval modal and resume via
    POST /api/resume-graph.

    config carries the thread_id: the graph is compiled WITH a checkpointer
    now, so every run must pass {"configurable": {"thread_id": ...}}. We reuse
    report_id as the thread_id, so the paused run and its archived report
    share one identifier.
    """
    config = {"configurable": {"thread_id": report_id}}
    final_report = None
    guardrail_passed = None
    run_symbols: dict[str, str] = {}

    try:
        async for event in graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            kind = event["event"]
            name = event.get("name", "")
            run_id = event.get("run_id")

            if kind == "on_chain_start" and name in _STATUS_NODES:
                metadata = {}
                if name == "sentiment_agent":
                    node_input = event.get("data", {}).get("input")
                    if isinstance(node_input, dict) and node_input.get("symbol"):
                        symbol = node_input["symbol"]
                        metadata["symbol"] = symbol
                        if run_id is not None:
                            run_symbols[run_id] = symbol
                yield _format_sse(
                    "status", {"node": name, "phase": "start", "metadata": metadata}
                )

            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict):
                    if output.get("final_report") is not None:
                        final_report = output["final_report"]
                    if "guardrail_passed" in output:
                        guardrail_passed = output["guardrail_passed"]
                if name in _STATUS_NODES:
                    metadata = {}
                    if name == "sentiment_agent" and run_id in run_symbols:
                        metadata["symbol"] = run_symbols[run_id]
                    yield _format_sse(
                        "status", {"node": name, "phase": "end", "metadata": metadata}
                    )

    except Exception as exc:  # noqa: BLE001 — the stream must surface, not swallow
        logger.exception(
            "generate-report stream failed for state=%s", initial_state.get("user_id")
        )
        yield _format_sse("error", {"code": "GRAPH_ERROR", "message": str(exc)})
        return

    if final_report is None:
        yield _format_sse(
            "error",
            {
                "code": "NO_REPORT",
                "message": "Graph finished without a final_report in state.",
            },
        )
        return

    payload = (
        final_report.model_dump(mode="json")
        if hasattr(final_report, "model_dump")
        else final_report
    )

    try:
        _persist_report(report_id, initial_state["user_id"], payload, guardrail_passed)
    except Exception:  # noqa: BLE001 — never deny a result over a failed archive
        logger.exception(
            "Failed to persist report %s for %s",
            report_id,
            initial_state.get("user_id"),
        )

    # Deliver the report whether or not memory review is pending — the report
    # is never held hostage to approval (design decision).
    yield _format_sse("report_complete", {**payload, "report_id": report_id})

    # V12b: deterministic "what changed since your last report" diff (no LLM).
    yield _format_sse("report_diff", _compute_report_diff(prev_report, payload))

    # V13: grade the previous report's recommendations against actual moves.
    yield _format_sse(
        "advice_review", _compute_advice_review(prev_report, prev_generated_at)
    )

    # V6: did the run pause at human_review's interrupt? Surface the proposals.
    try:
        snapshot = await graph.aget_state(config)
    except (
        Exception
    ) as exc:  # noqa: BLE001 — detection failure shouldn't error the report
        logger.warning(
            "interrupt detection: aget_state failed for %s — %s", report_id, exc
        )
        return

    paused = bool(snapshot.next) and "human_review" in snapshot.next
    if not paused:
        return

    # Prefer the interrupt payload; fall back to state for version robustness.
    proposed = []
    pend = list(getattr(snapshot, "interrupts", None) or [])
    if not pend:
        pend = [i for t in snapshot.tasks for i in getattr(t, "interrupts", ())]
    if pend and isinstance(getattr(pend[0], "value", None), dict):
        proposed = pend[0].value.get("proposed_memories", [])
    if not proposed:
        proposed = (snapshot.values or {}).get("proposed_memories", [])

    yield _format_sse(
        "human_input_required",
        {
            "thread_id": report_id,
            "type": "memory_review",
            "payload": {"proposed_memories": proposed},
        },
    )


@router.get(
    "/api/generate-report",
    summary="Stream a portfolio report for a user via SSE",
)
async def generate_report(
    user_id: str,
    token: str = "",
    db: Session = Depends(get_db),
    graph=Depends(get_graph),
) -> StreamingResponse:
    """Stream the LangGraph run for the user's stored portfolio over SSE.

    Flow:
        1. Lookup User + Portfolio by user_id (sync, at the boundary).
        2. 404 if either is missing.
        3. Read assets + risk_profile into a plain initial_state dict.
        4. Mint report_id (also the V6 checkpointer thread_id).
        5. Hand a request-session-free event generator to StreamingResponse.

    GET (not POST) because the browser's native EventSource only supports
    GET; the portfolio is resolved server-side from user_id.
    """
    # V9: EventSource can't set headers, so the token rides as a query param.
    # Derive the caller from the verified token and enforce ownership.
    # V15a: the curated demo user may generate without a token (read-only guest).
    if user_id != DEMO_USER_ID and verify_token(token) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only generate your own report.",
        )

    user = db.get(User, user_id)
    if user is None or user.portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No portfolio found for user_id '{user_id}'.",
        )

    initial_state = {
        "user_id": user_id,
        "portfolio": user.portfolio.assets,
        "risk_profile": user.risk_profile,
    }
    # Generated here so it can be reused as the V6 checkpointer thread_id
    # and returned to the client in report_complete.
    report_id = str(uuid4())

    # V12b: the most recent prior report (if any) for the since-last-report diff.
    # Fetched at the boundary with the request session, before the run starts.
    prev = (
        db.query(Report)
        .filter(Report.user_id == user_id)
        .order_by(Report.generated_at.desc())
        .first()
    )
    prev_report = prev.raw_result if prev else None
    prev_generated_at = prev.generated_at if prev else None

    return StreamingResponse(
        _report_event_stream(
            graph, initial_state, report_id, prev_report, prev_generated_at
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering (no-op locally)
        },
    )


class ResumeRequest(BaseModel):
    """Body for POST /api/resume-graph — the user's memory-approval decisions."""

    approved_indices: list[int] = Field(default_factory=list)


async def _resume_event_stream(graph, thread_id: str, approved_indices: list[int]):
    """Resume a paused graph from its checkpoint and stream the result (V6).

    Uses ainvoke(Command(resume=...)) rather than astream_events: the resume
    runs human_review -> memory_saver -> END with no LLM calls, so a single
    run-to-completion is simpler and more reliable than mapping a resumed event
    firehose (which is inconsistent across LangGraph versions). We synthesize
    the memory_saver status events around it and read what was saved from the
    returned final state.
    """
    config = {"configurable": {"thread_id": thread_id}}

    # Guard: only resume a run actually paused at human_review. An unknown or
    # already-finished thread_id makes Command(resume=...) misbehave; reject it.
    try:
        snapshot = await graph.aget_state(config)
    except Exception as exc:  # noqa: BLE001
        yield _format_sse("error", {"code": "RESUME_ERROR", "message": str(exc)})
        return
    if not (snapshot.next and "human_review" in snapshot.next):
        yield _format_sse(
            "error",
            {
                "code": "NO_PAUSED_RUN",
                "message": f"No paused memory review found for thread_id '{thread_id}'.",
            },
        )
        return

    yield _format_sse(
        "status", {"node": "memory_saver", "phase": "start", "metadata": {}}
    )
    try:
        result = await graph.ainvoke(
            Command(resume={"approved_indices": approved_indices}),
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("resume-graph failed for thread_id=%s", thread_id)
        yield _format_sse("error", {"code": "RESUME_ERROR", "message": str(exc)})
        return

    saved = (result or {}).get("new_memories", [])
    yield _format_sse(
        "status", {"node": "memory_saver", "phase": "end", "metadata": {}}
    )
    yield _format_sse("memory_saved", {"count": len(saved)})


@router.post(
    "/api/resume-graph", summary="Resume an interrupted graph with user decisions"
)
async def resume_graph(
    thread_id: str,
    payload: ResumeRequest,
    graph=Depends(get_graph),
    current_user: str = Depends(require_user),
) -> StreamingResponse:
    """Resume the memory-review interrupt for thread_id, streaming the rest.

    thread_id is the report_id from stream 1's human_input_required event.
    POST (not GET) because the approvals ride in the request body, so the
    client consumes this with fetch()+ReadableStream rather than EventSource.
    """
    return StreamingResponse(
        _resume_event_stream(graph, thread_id, payload.approved_indices),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

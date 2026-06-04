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
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.base import get_db, SessionLocal
from app.db.models import User, Report
from app.graph.builder import graph as compiled_graph

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
    "synthesizer",
    "guardrail",
    "memory_extractor",
}


def get_graph():
    """Provider for the compiled LangGraph singleton.

    Graph is built once at module import (graph/builder.py). Returns the
    same instance per call; tests override via
    app.dependency_overrides[get_graph].
    """
    return compiled_graph


def _format_sse(event_type: str, data: dict) -> str:
    """Serialize one SSE message: an `event:` line, a `data:` JSON line,
    terminated by a blank line per the SSE spec."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _persist_report(report_id: str, user_id: str, payload: dict) -> None:
    """Archive a finished report to the reports table (V5).

    Opens its OWN short-lived session — NOT the request's get_db session.
    The generator stays free of the request session (which may close while
    the stream is still open); this session is opened, used for one insert,
    and closed within a single await-free window at the moment of the write.

    confidence_flag is a coarse label derived from the report's confidence.
    The V6 guardrail may set this instead once it exists.
    """
    confidence = payload.get("confidence", 0.0)
    flag = "high" if confidence >= 0.6 else "low"
    db = SessionLocal()
    try:
        db.add(
            Report(
                id=report_id,
                user_id=user_id,
                raw_result=payload,
                confidence_flag=flag,
            )
        )
        db.commit()
    finally:
        db.close()


async def _report_event_stream(graph, initial_state: dict, report_id: str):
    """Async generator mapping the astream_events firehose to SSE events.

    Yields status events per node entry/exit, then exactly one terminal
    event: report_complete (carrying the FinalReport plus report_id) or
    error. The finished report is archived to the reports table (best
    effort) just before report_complete is emitted.
    """
    final_report = None
    # run_id -> symbol, so a sentiment_agent's end event can carry the same
    # symbol its start event did.
    run_symbols: dict[str, str] = {}

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
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
                    "status",
                    {"node": name, "phase": "start", "metadata": metadata},
                )

            elif kind == "on_chain_end":
                # Capture the report from whichever end event carries it.
                output = event.get("data", {}).get("output")
                if isinstance(output, dict) and output.get("final_report") is not None:
                    final_report = output["final_report"]
                if name in _STATUS_NODES:
                    metadata = {}
                    if name == "sentiment_agent" and run_id in run_symbols:
                        metadata["symbol"] = run_symbols[run_id]
                    yield _format_sse(
                        "status",
                        {"node": name, "phase": "end", "metadata": metadata},
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

    # final_report is a FinalReport instance off the State; mode="json"
    # keeps the payload JSON-clean regardless of field types.
    payload = (
        final_report.model_dump(mode="json")
        if hasattr(final_report, "model_dump")
        else final_report
    )

    # Archive at the boundary (best-effort) before announcing completion.
    try:
        _persist_report(report_id, initial_state["user_id"], payload)
    except Exception:  # noqa: BLE001 — never deny a result over a failed archive
        logger.exception(
            "Failed to persist report %s for %s",
            report_id,
            initial_state.get("user_id"),
        )

    # report_id rides alongside the report so the client can deep-link the
    # just-generated report to /history. It is an extra field on the
    # payload — the dashboard ignores it; the history view reads it.
    yield _format_sse("report_complete", {**payload, "report_id": report_id})


@router.get(
    "/api/generate-report",
    summary="Stream a portfolio report for a user via SSE",
)
async def generate_report(
    user_id: str,
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

    return StreamingResponse(
        _report_event_stream(graph, initial_state, report_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering (no-op locally)
        },
    )

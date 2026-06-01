"""
Routes for report generation.

V1: hardcoded portfolio {"AAPL": 10}, JSON return.
V2: portfolio fetched from DB by user_id. Graph signature unchanged.
V3: same handler, graph fans out internally to parallel agents.
V4: SSE streaming replaces the JSON return. The handler still does the
    DB lookup synchronously, then hands a self-contained event generator
    to StreamingResponse. graph.astream_events() drives the stream.
V6: this endpoint may emit human_input_required mid-stream; the client
    resumes against POST /api/resume-graph.

Architectural note — why DB lookup lives here, not in a node:
    The graph is a pure pipeline: portfolio_dict -> FinalReport. It does
    not know portfolios live in Postgres. This boundary is load-bearing
    for V8: the daily-digest scheduler will fetch every user's portfolio,
    loop, and pass each assets dict into the same graph. If DB access
    leaked into data_ingestion, the scheduler would have to re-fetch
    (waste) or special-case the node (entangle). Same reason makes the
    graph trivially testable — no DB fixtures, just a dict.

Architectural note — why the generator is DB-free:
    With StreamingResponse, the handler returns immediately and the
    generator runs while the response streams. Rather than reason about
    how long the get_db session stays alive across that window, we read
    everything we need (assets dict, risk_profile) into a plain
    initial_state dict BEFORE returning, and the generator touches only
    that dict and the compiled graph. No ORM objects cross into the
    stream. This is pattern #7 (API as I/O boundary) applied to SSE.

Why we don't emit `token` events in V4:
    The synthesizer uses .with_structured_output(FinalReport), so the
    model emits one JSON/tool-call object. Streaming its tokens yields
    partial JSON, not clean narrative prose. The `token` event type stays
    reserved in the taxonomy (§5.2) but is unused in V4. The streaming
    that carries the demo is the burst of `status` events from the N
    parallel sentiment_agent Send branches.

Why sentiment start/end are paired by run_id:
    Each parallel sentiment_agent Send branch is one runnable invocation,
    and astream_events gives that invocation a single run_id shared by its
    on_chain_start and on_chain_end events. The start event exposes the
    branch's symbol via data.input; the end event does not. So we stash
    run_id -> symbol on start and look it up on end, making every end
    event self-describing. Without this, end events are symbol-less and
    the frontend cannot match an end to the start branch it closes.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import User
from app.graph.builder import graph as compiled_graph

logger = logging.getLogger(__name__)

router = APIRouter()


# The graph node names we surface to the client as `status` events.
# astream_events emits on_chain_start/end for many runnables — the
# top-level graph, conditional-edge functions, prompts, chat models,
# parsers. Filtering on this set keeps the status feed to the four nodes
# the user cares about. Adding a node in a future version (memory_loader
# in V5, guardrail/human_review/memory_saver in V6) means adding its name
# here so it shows up in the feed.
_STATUS_NODES = {"data_ingestion", "sentiment_agent", "risk_agent", "synthesizer"}


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


async def _report_event_stream(graph, initial_state: dict):
    """Async generator mapping the astream_events firehose to SSE events.

    Yields, in wire order:
        - one `status` (phase=start) per node entry, with {"symbol": ...}
          metadata on sentiment_agent branches so the feed names the asset;
        - one `status` (phase=end) per node exit, with the same {"symbol"}
          on sentiment_agent branches (recovered via run_id) so the client
          can match each end to the start branch it closes;
        - exactly one terminal event: `report_complete` carrying the full
          FinalReport JSON, or `error` if the graph raised or finished
          without producing a report.

    Everything astream_events emits that is not an on_chain_start/end for
    a node in _STATUS_NODES is dropped. The final report is captured off
    whichever on_chain_end carries it.
    """
    final_report = None
    # run_id -> symbol, so a sentiment_agent's end event can carry the same
    # symbol its start event did. Cleared implicitly when the stream ends.
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
        logger.exception("generate-report stream failed for state=%s", initial_state.get("user_id"))
        yield _format_sse("error", {"code": "GRAPH_ERROR", "message": str(exc)})
        return

    if final_report is None:
        yield _format_sse(
            "error",
            {"code": "NO_REPORT", "message": "Graph finished without a final_report in state."},
        )
        return

    # final_report is a FinalReport instance off the State; mode="json"
    # keeps the payload JSON-clean regardless of field types.
    payload = (
        final_report.model_dump(mode="json")
        if hasattr(final_report, "model_dump")
        else final_report
    )
    yield _format_sse("report_complete", payload)


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
        4. Hand a DB-free event generator to StreamingResponse.

    GET (not POST) because the browser's native EventSource only supports
    GET; the portfolio is resolved server-side from user_id. No
    response_model here — a streaming body has no single fixed schema.
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

    return StreamingResponse(
        _report_event_stream(graph, initial_state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering (no-op locally)
        },
    )

"""
Routes for report generation.

V1: hardcoded portfolio {"AAPL": 10}.
V2: portfolio fetched from DB by user_id. Graph signature unchanged.
V3: same handler, graph fans out internally to parallel agents.
V4: streaming variant via SSE replaces the JSON return.
V6: this endpoint may emit human_input_required mid-stream; the
    client resumes against POST /api/resume-graph.

Architectural note — why DB lookup lives here, not in a node:
    The graph is a pure pipeline: portfolio_dict → FinalReport. It
    does not know portfolios live in Postgres. This boundary is
    load-bearing for V8: the daily-digest scheduler will fetch
    every user's portfolio, loop, and pass each assets dict into
    the same graph. If DB access leaked into data_ingestion, the
    scheduler would have to re-fetch (waste) or special-case the
    node (entangle). Same reason makes the graph trivially testable
    — no DB fixtures, just a dict.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import User
from app.graph.builder import graph as compiled_graph
from app.schemas.report import FinalReport

router = APIRouter()


def get_graph():
    """Provider for the compiled LangGraph singleton.

    Graph is built once at module import (graph/builder.py). Returns
    the same instance per call; tests override via
    app.dependency_overrides[get_graph].
    """
    return compiled_graph


@router.get(
    "/api/generate-report",
    response_model=FinalReport,
    summary="Generate a portfolio report for a user",
)
async def generate_report(
    user_id: str,
    db: Session = Depends(get_db),
    graph=Depends(get_graph),
) -> FinalReport:
    """Run the LangGraph end-to-end against the user's stored portfolio.

    Flow:
        1. Lookup User + Portfolio by user_id.
        2. 404 if either is missing.
        3. Hand the assets dict to the graph.
        4. Return the synthesizer's FinalReport.

    risk_profile is read but not yet propagated into State — V3
    introduces the risk_agent and extends PortfolioState to carry it.
    Holding off here keeps V2 narrowly scoped to "swap the source of
    the portfolio dict, leave the graph alone."

    Concurrency note:
        db.get() is sync and briefly blocks the event loop. Negligible
        at MVP scale. The session stays open during graph.ainvoke()
        (LLM round-trips can be several seconds). Fine for single-user
        demo; V8 multi-user digest will either release the session
        earlier or move to async SQLAlchemy.
    """
    user = db.get(User, user_id)
    if user is None or user.portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No portfolio found for user_id '{user_id}'.",
        )

    # The graph's input contract is identical to V1/V2 in shape — only
    # the keys grow over versions. risk_profile joins the inputs in V3
    # because risk_agent (V3 step 4) consumes it.
    initial_state = {
        "user_id": user_id,
        "portfolio": user.portfolio.assets,
        "risk_profile": user.risk_profile,
    }

    final_state = await graph.ainvoke(initial_state)
    return final_state["final_report"]

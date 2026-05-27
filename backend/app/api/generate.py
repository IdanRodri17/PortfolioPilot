"""
Routes for report generation.

V1 exposes a single GET endpoint that invokes the compiled LangGraph
for a hardcoded demo portfolio and returns the resulting FinalReport.
V2 will replace the hardcoded portfolio with a DB lookup.

The compiled graph is injected via Depends(get_graph). This keeps the
handler decoupled from the graph singleton (testable in isolation via
app.dependency_overrides) and makes the graph's role at the boundary
explicit.
"""

from fastapi import APIRouter, Depends

from app.graph.builder import graph as compiled_graph
from app.schemas.report import FinalReport

router = APIRouter()


def get_graph():
    """Provider for the compiled LangGraph singleton.

    The graph is built once at module import (see graph/builder.py).
    This provider returns the same instance for every request.
    No @lru_cache needed — the singleton lives at module scope already;
    this function is a cheap pointer return.

    In tests, override via app.dependency_overrides[get_graph].
    """
    return compiled_graph


@router.get(
    "/api/generate-report",
    response_model=FinalReport,
    summary="Generate a portfolio report for a user",
)
async def generate_report(
    user_id: str,
    graph=Depends(get_graph),
) -> FinalReport:
    """Run the LangGraph end-to-end and return the FinalReport.

    V1 uses a hardcoded portfolio. V2 reads from the portfolios table
    keyed by user_id.
    """
    # V1: hardcoded portfolio. Replaced by DB read in V2.
    portfolio = {"AAPL": 10.0}

    initial_state = {
        "user_id": user_id,
        "portfolio": portfolio,
    }

    final_state = await graph.ainvoke(initial_state)
    return final_state["final_report"]

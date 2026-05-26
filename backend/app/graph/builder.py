"""
LangGraph builder — wires nodes into a compiled, runnable graph.

The compiled graph is built once at module import and exposed as the
module-level `graph` symbol. Downstream code (FastAPI handlers, tests)
imports this singleton and reuses it. Never re-compile per request.

Versioning:
    V1: linear data_ingestion -> synthesizer -> END.
    V3: conditional fan-out after data_ingestion to parallel
        sentiment_agents (one per asset) + risk_agent; synthesizer
        becomes the merge point.
    V5: memory_loader prepended; memory_extractor appended.
    V6: guardrail cycle between synthesizer and memory chain;
        human_review interrupt + PostgresSaver checkpointer attached
        at compile time via the _build_graph factory's parameters.
"""

from langgraph.graph import StateGraph, START, END

from app.graph.state import PortfolioState
from app.graph.nodes.data_ingestion import data_ingestion
from app.graph.nodes.synthesizer import synthesizer


def _build_graph():
    """Construct and compile the V1 PortfolioPilot graph.

    Wrapped in a factory function (rather than inline at module scope)
    so V6 can extend the signature to accept a checkpointer for HITL
    support without restructuring this file.
    """
    builder = StateGraph(PortfolioState)

    # Register nodes by name. Edges refer to these names, not the
    # function objects, so V3 can swap the implementation behind a
    # node name without rewiring the graph.
    builder.add_node("data_ingestion", data_ingestion)
    builder.add_node("synthesizer", synthesizer)

    # Static edges form the linear pipeline.
    # START and END are sentinel pseudo-nodes; not callables.
    builder.add_edge(START, "data_ingestion")
    builder.add_edge("data_ingestion", "synthesizer")
    builder.add_edge("synthesizer", END)

    # compile() validates topology and returns a Pregel runnable.
    return builder.compile()


# Module-level singleton. Importers get the same compiled graph.
graph = _build_graph()

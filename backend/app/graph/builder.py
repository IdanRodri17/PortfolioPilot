"""
LangGraph builder — wires nodes into a compiled, runnable graph.

The compiled graph is built once at module import and exposed as the
module-level `graph` symbol. Downstream code (FastAPI handlers, tests)
imports this singleton and reuses it.

Versioning:
    V1: linear data_ingestion → synthesizer → END.
    V2: identical topology; DB lookup moved to handler.
    V3: data_ingestion fans out (via Send) to N sentiment_agents +
        1 risk_agent. Synthesizer is the implicit barrier — it fires
        only when every Send branch has completed and the reducer
        has merged sentiment_findings into State.
    V5: memory_loader prepended; memory_extractor appended.
    V6: guardrail cycle between synthesizer and memory chain;
        human_review interrupt + PostgresSaver checkpointer attached
        at compile time via _build_graph's parameters.
"""

from typing import List

from langgraph.constants import Send
from langgraph.graph import StateGraph, START, END

from app.graph.state import PortfolioState
from app.graph.nodes.data_ingestion import data_ingestion
from app.graph.nodes.synthesizer import synthesizer
from app.graph.nodes.sentiment_agent import sentiment_agent
from app.graph.nodes.risk_agent import risk_agent


def fan_out_to_agents(state: PortfolioState) -> List[Send]:
    """Conditional edge: spawn one sentiment_agent per symbol + one risk_agent.

    Returns a list of Send objects rather than a single node-name string.
    LangGraph spawns each Send as an independent, concurrent invocation
    of its target node. The Send's payload dict IS the State that
    invocation sees — so we splat the upstream state and override
    per-branch fields (only `symbol` differs between sentiment branches).

    Note on coverage:
        We fan out over portfolio.keys(), not market_data.keys(). A
        symbol whose yfinance call failed in data_ingestion still gets
        a sentiment_agent branch — sentiment is grounded in Tavily news,
        not in price. The synthesizer still receives that insight; only
        portfolio_valuation excludes the unpriced asset.

    Note on merge:
        All sentiment_agent branches return {"sentiment_findings": [x]}
        and the Annotated[List[dict], add] reducer concatenates them.
        risk_agent returns {"risk_analysis": {...}} to a single-writer
        field. By the time synthesizer fires, both fields are fully
        populated. No explicit wait/join — the edges below provide
        implicit barrier sync.
    """
    sends: List[Send] = [
        Send("sentiment_agent", {**state, "symbol": symbol})
        for symbol in state["portfolio"].keys()
    ]
    sends.append(Send("risk_agent", state))
    return sends


def _build_graph():
    """Construct and compile the V3 PortfolioPilot graph.

    Topology:
        START → data_ingestion → [fan_out_to_agents]
                                  ├─→ sentiment_agent (× N) ─┐
                                  └─→ risk_agent ────────────┴─→ synthesizer → END

    The list arg ["sentiment_agent", "risk_agent"] on add_conditional_edges
    is the enumeration of all possible Send targets — required by
    LangGraph for static graph validation. Adding a new fan-out target
    in a future version (e.g., a macro_context_agent) requires updating
    this list too.
    """
    builder = StateGraph(PortfolioState)

    builder.add_node("data_ingestion", data_ingestion)
    builder.add_node("sentiment_agent", sentiment_agent)
    builder.add_node("risk_agent", risk_agent)
    builder.add_node("synthesizer", synthesizer)

    builder.add_edge(START, "data_ingestion")

    # Fan-out: data_ingestion's "next" is determined dynamically by
    # fan_out_to_agents returning a list of Sends, NOT by a single
    # string node-name. This is what makes Send distinct from a
    # regular conditional edge.
    builder.add_conditional_edges(
        "data_ingestion",
        fan_out_to_agents,
        ["sentiment_agent", "risk_agent"],  # all possible Send targets
    )

    # Implicit barrier: synthesizer fires only after every Send branch
    # has completed. LangGraph handles the wait; no explicit join.
    builder.add_edge("sentiment_agent", "synthesizer")
    builder.add_edge("risk_agent", "synthesizer")

    builder.add_edge("synthesizer", END)

    return builder.compile()


# Module-level singleton. Importers get the same compiled graph.
graph = _build_graph()

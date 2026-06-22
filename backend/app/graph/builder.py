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
    V5: memory_loader prepended as the entrypoint; the graph is compiled
        WITH the PostgresStore so LangGraph can inject it into memory
        nodes. memory_extractor appended in step 5.
    V6: guardrail cycle between synthesizer and memory chain;
        human_review interrupt + PostgresSaver checkpointer attached
        at compile time via _build_graph's parameters.
"""

from typing import List

from langgraph.constants import Send
from langgraph.graph import StateGraph, START, END
from langgraph.store.base import BaseStore

from app.graph.state import PortfolioState
from app.graph.persistence.store import store as memory_store
from app.graph.nodes.data_ingestion import data_ingestion
from app.graph.nodes.synthesizer import synthesizer
from app.graph.nodes.sentiment_agent import sentiment_agent
from app.graph.nodes.risk_agent import risk_agent
from app.graph.nodes.macro_context_agent import macro_context_agent
from app.graph.nodes.memory_loader import memory_loader
from app.graph.nodes.memory_extractor import memory_extractor
from app.graph.nodes.guardrail import guardrail, route_after_guardrail
from app.graph.nodes.human_review import human_review
from app.graph.nodes.memory_saver import memory_saver


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
        risk_agent and macro_context_agent each return a dict to their own
        single-writer field ({"risk_analysis": ...} / {"macro_analysis": ...}).
        By the time synthesizer fires, all three are fully populated. No
        explicit wait/join — the edges below provide implicit barrier sync.
    """
    sends: List[Send] = [
        Send("sentiment_agent", {**state, "symbol": symbol})
        for symbol in state["portfolio"].keys()
    ]
    sends.append(Send("risk_agent", state))
    sends.append(Send("macro_context_agent", state))
    return sends


def _build_graph(store: BaseStore | None = None, checkpointer=None):
    """Construct and compile the PortfolioPilot graph.

    Topology (V11):
        START → memory_loader → data_ingestion → [fan_out_to_agents]
                                                  ├─→ sentiment_agent (× N) ─┐
                                                  ├─→ risk_agent ────────────┤
                                                  └─→ macro_context_agent ───┴─→ synthesizer → guardrail → … → END

    The list arg on add_conditional_edges enumerates all possible Send targets —
    required by LangGraph for static graph validation. macro_context_agent (V11)
    joins sentiment_agent and risk_agent there; any future fan-out target must be
    added to that list AND given an edge into synthesizer so the implicit barrier
    waits for it.

    store: the PostgresStore handed to compile(). Passing it here is what
    makes LangGraph inject it into any node whose signature requests
    `store: BaseStore` — memory_loader and memory_extractor. Defaulted to
    None so tests can compile a store-less graph (or inject a fake). V6
    adds a `checkpointer=` parameter the same way.
    """
    builder = StateGraph(PortfolioState)

    builder.add_node("memory_loader", memory_loader)
    builder.add_node("data_ingestion", data_ingestion)
    builder.add_node("sentiment_agent", sentiment_agent)
    builder.add_node("risk_agent", risk_agent)
    builder.add_node("macro_context_agent", macro_context_agent)
    builder.add_node("synthesizer", synthesizer)
    builder.add_node("memory_extractor", memory_extractor)
    builder.add_node("guardrail", guardrail)
    builder.add_node("human_review", human_review)
    builder.add_node("memory_saver", memory_saver)

    # memory_loader runs first: it reads portfolio + risk_profile (both in
    # the initial_state from the handler) and loads long_term_memory before
    # any market data is fetched. It needs nothing from data_ingestion.
    builder.add_edge(START, "memory_loader")
    builder.add_edge("memory_loader", "data_ingestion")

    # Fan-out: data_ingestion's "next" is determined dynamically by
    # fan_out_to_agents returning a list of Sends, NOT by a single
    # string node-name. This is what makes Send distinct from a
    # regular conditional edge.
    builder.add_conditional_edges(
        "data_ingestion",
        fan_out_to_agents,
        # all possible Send targets
        ["sentiment_agent", "risk_agent", "macro_context_agent"],
    )

    # Implicit barrier: synthesizer fires only after every Send branch
    # has completed. LangGraph handles the wait; no explicit join.
    builder.add_edge("sentiment_agent", "synthesizer")
    builder.add_edge("risk_agent", "synthesizer")
    builder.add_edge("macro_context_agent", "synthesizer")

    # memory_extractor runs last: it distills durable insights from the
    # finished report and persists them, so the next run's memory_loader
    # surfaces them. This closes the learning loop.
    builder.add_edge("synthesizer", "guardrail")
    builder.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        [
            "synthesizer",
            "memory_extractor",
        ],  # all possible targets (cycle back or proceed)
    )
    builder.add_edge("memory_extractor", "human_review")
    builder.add_edge("human_review", "memory_saver")
    builder.add_edge("memory_saver", END)

    # Compiling WITH the store is what enables store injection into nodes.
    return builder.compile(store=store, checkpointer=checkpointer)


# Module-level singleton, compiled with the PostgresStore singleton.
# Importers get the same compiled graph.
graph = _build_graph(store=memory_store)


def set_checkpointer(checkpointer) -> None:
    """Recompile the graph singleton WITH the checkpointer.

    Called once from main.py's lifespan, because the async checkpointer must be
    constructed inside a running event loop (it binds to the loop in __init__).
    At import there is no loop, so the singleton above is compiled store-only;
    the lifespan upgrades it in place before any request is served.
    """
    global graph
    graph = _build_graph(store=memory_store, checkpointer=checkpointer)

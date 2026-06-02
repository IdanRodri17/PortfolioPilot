"""
memory_loader node — retrieves relevant long-term memories (V5).

Runs first in the V5 graph (START → memory_loader → data_ingestion, wired
in step 3b). Builds a semantic query describing the user's current
situation, searches the PostgresStore, and loads the top-K most relevant
past insights into State for the synthesizer to weave into the report.

Store injection:
    The node takes a keyword-only `store: BaseStore` parameter. When the
    graph is compiled with builder.compile(store=store) (step 3b),
    LangGraph injects the compiled store into any node whose signature
    asks for it — the same dependency-injection mechanism as `config`.
    The node never imports the store singleton directly: it depends on
    what it's handed, which keeps it unit-testable (pass a store in) and
    leaves lifecycle to the framework.

On graph purity (pattern #7):
    Earlier nodes do no I/O — DB access lives at the API boundary so the
    V8 scheduler can reuse the graph against a different data source.
    memory_loader DOES do I/O, but to the graph's OWN memory (the store),
    not to the application's request-scoped DB session. Remembering across
    runs is intrinsic to what this graph is, and the store is injected, not
    hardcoded — so the scheduler reuses the same compiled graph and gets the
    same memory behavior for free. The principle (inject dependencies, don't
    entangle with the app's DB session) holds.

Versioning:
    V5: semantic retrieval into long_term_memory (this file).
    V6: unchanged here — the human-approval split happens on the WRITE side
        (memory_extractor proposes → human_review → memory_saver persists).
"""

import logging
from typing import Dict

from langgraph.store.base import BaseStore

from app.graph.state import PortfolioState

logger = logging.getLogger(__name__)

# Top-K memories to surface. 5 keeps the synthesizer prompt focused —
# the most relevant handful, not the full memory history. The store
# returns them already ordered by cosine similarity, so "top 5" means
# "the 5 most relevant to the current portfolio + risk posture".
_MEMORY_LIMIT = 5


def _build_query(portfolio: Dict[str, float], risk_profile: str) -> str:
    """Compose the natural-language query that gets embedded and matched.

    The query describes the user's CURRENT situation — their holdings and
    risk posture — so semantic search surfaces past insights relevant to
    *this* portfolio rather than every memory ever stored. The query text
    only needs to live in the same semantic neighborhood as the stored
    insights; it does not need to be a question.
    """
    symbols = ", ".join(sorted(portfolio.keys())) or "no current holdings"
    return (
        f"Investment preferences and past decisions for a {risk_profile} "
        f"investor currently holding: {symbols}."
    )


def memory_loader(state: PortfolioState, *, store: BaseStore) -> dict:
    """Load the top-K most relevant long-term memories for this user.

    Reads:
        state["user_id"], state["portfolio"], state["risk_profile"].

    Returns:
        {"long_term_memory": [value_dict, ...]} — most relevant first.
        Empty list when the user has no memories yet (every first run) or
        if retrieval fails (see degradation note).

    Namespace:
        ("memories", user_id) — memories are partitioned per user, so one
        user's insights never leak into another's search results.

    Graceful degradation (pattern #22):
        A store failure should not 500 the whole report. On error we log
        and return an empty memory list; the synthesizer simply generates a
        report without historical context (and step 4's prompt treats
        absent memory as the normal first-run case). Memory is enrichment,
        not a hard dependency of report generation.
    """
    user_id = state["user_id"]
    namespace = ("memories", user_id)
    query = _build_query(state["portfolio"], state["risk_profile"])

    try:
        results = store.search(namespace, query=query, limit=_MEMORY_LIMIT)
    except Exception as exc:  # noqa: BLE001 — degrade, don't crash the report
        logger.warning("memory_loader: store search failed for %s — %s", user_id, exc)
        return {"long_term_memory": []}

    memories = [r.value for r in results]
    logger.info("memory_loader: loaded %d memories for %s", len(memories), user_id)
    return {"long_term_memory": memories}

"""
memory_extractor node — distills durable user insights and saves them (V5).

Runs last in the V5 graph (synthesizer -> memory_extractor -> END). After a
report is produced, it proposes 0-3 NEW durable insights about the user's
investing style and persists them to the PostgresStore, so future reports
(via memory_loader) become more personalized.

V5 vs V6 (important):
    In V5, proposed insights are persisted AUTOMATICALLY here. In V6 this
    node splits: memory_extractor only PROPOSES, a human_review interrupt()
    lets the user approve, and a separate memory_saver persists only the
    approved ones. new_memories carries what was saved (V5) / proposed (V6).

Deduplication:
    The node receives the memories already retrieved this run
    (long_term_memory) and is told not to repeat them, so the store doesn't
    fill with restatements of the same observation.

Graceful degradation (pattern #22):
    The report is already complete by the time this node runs (the
    synthesizer's output was captured upstream), so a store-write failure
    must never sink it. On error we log and return what was saved (possibly
    nothing). Memory is enrichment, not a hard dependency.
"""

import logging
from typing import List

from langgraph.store.base import BaseStore
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from app.graph.state import PortfolioState
from app.schemas.report import FinalReport

logger = logging.getLogger(__name__)

_MAX_MEMORIES = 3


class _ProposedMemories(BaseModel):
    """Structured-output schema for the extraction call."""

    insights: List[str] = Field(
        default_factory=list,
        description=(
            "Between 0 and 3 NEW, durable, user-specific insights worth "
            "remembering for future reports. Each is one concise sentence "
            "about the user's investing style, risk behavior, sector tilts, "
            "concentration tendencies, or evident preferences — NOT transient "
            "market facts, prices, sentiment, or restatements of this report. "
            "Return an empty list if nothing new and durable is worth saving."
        ),
    )


SYSTEM_PROMPT = (
    "You are the memory module of PortfolioPilot, an AI wealth manager. "
    "After each portfolio report, distill DURABLE, reusable insights about "
    "THIS user — their investing style, preferences, risk posture, and "
    "positioning patterns — that would help personalize FUTURE reports. You "
    "are not summarizing the report; you are learning about the person "
    "behind the portfolio."
)

HUMAN_PROMPT = (
    "User portfolio (risk profile: {profile_name}):\n"
    "{portfolio_block}\n\n"
    "Recommendations made in this report:\n"
    "{recommendations_block}\n\n"
    "Report narrative:\n"
    "{narrative}\n\n"
    "What we ALREADY remember about this user (do NOT repeat or lightly "
    "reword any of these):\n"
    "{existing_memory_block}\n\n"
    "Propose between 0 and 3 NEW durable insights worth remembering:\n"
    "  - Durable, user-level facts only: investing style, risk behavior, "
    "sector tilts, concentration tendencies, evident preferences. NOT "
    "transient market facts, prices, sentiment, or one-off events.\n"
    "  - Each is one concise sentence written about the user.\n"
    "  - Do NOT restate the report or repeat anything already remembered.\n"
    "  - If nothing new and durable is worth saving, return an empty list. "
    "An empty list is often the correct answer."
    "  - Each is one concise sentence written about the user.\n"
    "  - Do NOT restate the report or repeat anything already remembered.\n"
    "  - Do NOT restate the user's stated risk profile or current holdings "
    "as an insight — those are given inputs, not learned observations.\n"
    "  - Do NOT assume the user accepted or acted on any recommendation; the "
    "report's recommendations are the system's suggestions, not the user's "
    "decisions.\n"
    "  - If nothing new and durable is worth saving, return an empty list. "
    "An empty list is often the correct answer."
)

_prompt = ChatPromptTemplate.from_messages(
    [("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]
)
# Cheap model — extraction is a focused, low-token task (SRS §2).
_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
_chain = _prompt | _llm.with_structured_output(_ProposedMemories)


# ─── Prompt formatters ──────────────────────────────────────────────


def _format_portfolio_block(portfolio: dict) -> str:
    if not portfolio:
        return "(empty portfolio)"
    return ", ".join(f"{sym}: {qty}" for sym, qty in sorted(portfolio.items()))


def _format_recommendations_block(report: FinalReport) -> str:
    recs = report.rebalancing_recommendations
    if not recs:
        return "(no rebalancing recommendations — composition within profile)"
    return "\n".join(
        f"- {r.action} {r.asset} ({r.target_change_pct:+.1f}%): {r.rationale}"
        for r in recs
    )


def _format_existing_memory_block(memories: List[dict]) -> str:
    if not memories:
        return "(nothing remembered yet)"
    lines = [f"- {m['insight']}" for m in memories if m.get("insight")]
    return "\n".join(lines) if lines else "(nothing remembered yet)"


# ─── Node ─────────────────────────────────────────────────────────────


def memory_extractor(state: PortfolioState) -> dict:
    """Propose durable insights from the finished report (V6: propose-only).

    V5 also persisted here; V6 narrows this node to proposing only. The
    human_review interrupt then lets the user approve, and memory_saver
    persists the approved subset. This node no longer touches the store.

    Reads:
        user_id, portfolio, risk_profile, final_report,
        long_term_memory (for dedup).

    Returns:
        {"proposed_memories": [{"insight": str}, ...]} — 0-3 candidates,
        nothing persisted yet.
    """
    user_id = state["user_id"]
    report: FinalReport = state["final_report"]
    portfolio = state["portfolio"]
    risk_profile = state["risk_profile"]
    existing = state.get("long_term_memory", [])

    try:
        proposed = _chain.invoke(
            {
                "profile_name": risk_profile,
                "portfolio_block": _format_portfolio_block(portfolio),
                "recommendations_block": _format_recommendations_block(report),
                "narrative": report.summary_narrative,
                "existing_memory_block": _format_existing_memory_block(existing),
            }
        )
    except Exception as exc:  # noqa: BLE001 — report is done; never sink it
        logger.warning("memory_extractor: proposal failed for %s — %s", user_id, exc)
        return {"proposed_memories": []}

    candidates: List[dict] = []
    for insight in proposed.insights[:_MAX_MEMORIES]:
        text = insight.strip()
        if text:
            candidates.append({"insight": text})

    logger.info(
        "memory_extractor: proposed %d insights for %s", len(candidates), user_id
    )
    return {"proposed_memories": candidates}

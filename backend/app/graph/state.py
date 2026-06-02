"""
LangGraph state schema for PortfolioPilot.

The State is the data envelope that flows through every node in the graph.
Each node reads from it and returns a partial dict of updates; LangGraph
merges those updates back into the State before the next node runs.

Why TypedDict and not Pydantic:
    LangGraph mutates the State on every node return and (in V3+) on every
    parallel reducer merge. TypedDict is a zero-cost type hint over plain
    dict — no validation overhead, no copy semantics. Pydantic is reserved
    for boundaries (API contracts, LLM structured output).

Reducer pattern (V3+):
    A reducer is a binary function LangGraph calls to *combine* an existing
    State value with an incoming update, instead of overwriting. Declared
    via `Annotated[type, reducer_fn]`. Without a reducer, parallel branches
    writing to the same field clobber each other — last-write-wins.

    `sentiment_findings: Annotated[List[dict], add]` means each parallel
    sentiment_agent returns a single-item list (e.g. [aapl_insight]) and
    the `add` reducer (which is just list concatenation via `+`) folds
    every branch's contribution into a single accumulated list.

    Fields written by exactly one node do NOT need a reducer — the
    default overwrite semantics are correct. `risk_analysis` is the
    canonical single-writer case here.

Versioning:
    V1: minimal — only fields for the linear data_ingestion → synthesizer flow.
    V2: unchanged (DB lookup happens at the API boundary, not in State).
    V3: + sentiment_findings (with reducer), risk_analysis, risk_profile.
    V5: + long_term_memory.
    V6: + guardrail_passed, guardrail_feedback, retry_count,
          proposed_memories, approved_memories, new_memories.
    TypedDict fields are additive — growing the schema per version never
    breaks earlier code.
"""

from operator import add
from typing import TypedDict, Annotated, Dict, List, Any

from app.schemas.portfolio import RiskProfile
from app.schemas.report import FinalReport


class PortfolioState(TypedDict, total=False):
    # ─── Inputs (provided when calling graph.invoke()) ───
    user_id: str
    portfolio: Dict[str, float]
    # e.g. {"AAPL": 10, "BTC": 0.5} — float supports fractional crypto

    risk_profile: RiskProfile
    # "conservative" | "balanced" | "aggressive" — populated by the
    # handler from User.risk_profile (DB). Read by risk_agent (V3 step 4).

    # ─── Loaded by memory_loader (V5) ───
    long_term_memory: List[dict]
    # Past insights retrieved from PostgresStore via semantic search,
    # ordered most-relevant-first. Each element is a stored value dict,
    # e.g. {"insight": "...", "context": "..."}. Single writer
    # (memory_loader), so no reducer — default overwrite is correct.

    # ─── Populated by data_ingestion ───
    market_data: Dict[str, dict]
    # e.g. {"AAPL": {"price": 220.5, "change_24h_percent": 1.2}}

    # ─── Populated by parallel sentiment_agent branches (V3 step 3) ───
    # The `add` reducer is what makes parallel Send() fan-out safe.
    # Without it, the last branch to return clobbers the previous four
    # in a 5-symbol portfolio. Each branch returns a single-item list;
    # the reducer concatenates them into the final accumulated list.
    sentiment_findings: Annotated[List[dict], add]

    # Populated by risk_agent (V3 step 4)
    symbol: str

    # Single writer, no reducer needed. Type stays loose (dict) until
    # Step 4 lands a Pydantic RiskAnalysis schema if it earns its keep.
    risk_analysis: Dict[str, Any]

    # ─── Populated by synthesizer ───
    final_report: FinalReport

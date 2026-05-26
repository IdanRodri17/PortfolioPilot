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

Versioning note:
    V1 keeps the State minimal — only the fields needed for the linear
    data_ingestion → synthesizer flow. Later versions extend this schema:
      - V3: sentiment_findings (Annotated reducer), risk_analysis
      - V5: long_term_memory
      - V6: guardrail_passed/feedback/retry_count, proposed_memories,
            approved_memories, new_memories
    TypedDict fields are additive, so growing the schema per version
    never breaks earlier code.
"""

from typing import TypedDict, Dict

from app.schemas.report import FinalReport


class PortfolioState(TypedDict, total=False):
    # ─── Inputs (provided when calling graph.invoke()) ───
    user_id: str
    portfolio: Dict[str, float]
    # e.g., {"AAPL": 10, "BTC": 0.5} — float supports fractional crypto

    # ─── Populated by data_ingestion ───
    market_data: Dict[str, dict]
    # e.g., {"AAPL": {"price": 220.5, "change_24h_percent": 1.2}}
    # Kept as Dict[str, dict] for V1 because the per-asset payload shape
    # will grow as we add news, volume, etc. — premature TypedDict-ing
    # would just churn.

    # ─── Populated by synthesizer ───
    final_report: FinalReport

"""
synthesizer node — turns market data into a structured FinalReport.

The LLM-calling node. Builds an LCEL chain at module import time and
uses .with_structured_output(FinalReport) so the model is constrained
at sampling time to emit only valid FinalReport JSON.

Versioning:
    V1: prompt receives portfolio + market_data only.
    V2: portfolio and market_data are rendered as markdown tables for
        readability at multi-asset scale, and the prompt flags any
        portfolio assets for which market data could not be fetched.
    V3: sentiment_findings and risk_analysis are injected (filled by
        upstream parallel agents).
    V5: long_term_memory is injected.
    V6: guardrail_feedback is injected on retry attempts.

The prompt template is parameterized to evolve over versions without
changing the surrounding chain wiring.
"""

from typing import Dict, Set

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.graph.state import PortfolioState
from app.schemas.report import FinalReport

SYSTEM_PROMPT = (
    "You are PortfolioPilot, an AI wealth-management assistant. "
    "You analyze portfolio holdings using the data provided and produce "
    "a structured report with per-asset insights, rebalancing "
    "recommendations, and a narrative summary. Stay grounded in the "
    "data — do not fabricate prices, news, or events that are not "
    "supported by the information given."
)

HUMAN_PROMPT = (
    "User portfolio:\n"
    "{portfolio_table}\n\n"
    "Latest market data:\n"
    "{market_data_table}\n\n"
    "{missing_assets_block}"
    "Produce a FinalReport for this portfolio. Compute valuation from "
    "quantities × prices for the priced assets — do not fabricate "
    "prices for any missing assets. Generate one MarketInsight per "
    "priced asset, basing sentiment on the 24h change and general "
    "knowledge of the company. Recommend rebalancing only when "
    "warranted by 24h moves; an empty list is acceptable. Write a "
    "2-3 paragraph narrative in plain prose. PortfolioPilot has no "
    "real news search yet, so self-assess confidence in the 0.4-0.6 "
    "range — lower further if any assets were missing data."
)

_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ]
)

# gpt-4o-mini for V1-V2 (cheap, fast, sufficient for the structured
# output task at hand). V3 upgrades to gpt-4o when the prompt grows
# substantially with sentiment + risk + memory context.
_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

_chain = _prompt | _llm.with_structured_output(FinalReport)


# ─── Prompt formatters ──────────────────────────────────────────────
# Kept as private helpers in this file because V2 has only one
# LLM-calling node. If V3's sentiment_agent or risk_agent end up
# rendering the same tables in their own prompts, extract to a shared
# module (app/graph/prompt_formatters.py) at that point — not before.


def _format_portfolio_table(portfolio: Dict[str, float]) -> str:
    """Render the portfolio dict as a small markdown table.

    Five assets in dict-repr form reads as one line of dense JSON. A
    markdown table is significantly easier for the LLM to align with
    rows of market_data below.
    """
    if not portfolio:
        return "(empty portfolio)"
    lines = ["| Symbol | Quantity |", "|--------|----------|"]
    for symbol, qty in portfolio.items():
        lines.append(f"| {symbol} | {qty} |")
    return "\n".join(lines)


def _format_market_data_table(market_data: Dict[str, dict]) -> str:
    """Render market_data as a markdown table aligned with the portfolio."""
    if not market_data:
        return "(no market data available)"
    lines = [
        "| Symbol | Price (USD) | 24h Change (%) |",
        "|--------|-------------|----------------|",
    ]
    for symbol, data in market_data.items():
        lines.append(f"| {symbol} | {data['price']} | {data['change_24h_percent']} |")
    return "\n".join(lines)


def _format_missing_assets_block(missing: Set[str]) -> str:
    """Render a one-paragraph note for portfolio assets without market data.

    Returns empty string when nothing is missing — the prompt template
    is laid out so an empty block does not leave double whitespace.
    """
    if not missing:
        return ""
    listing = ", ".join(sorted(missing))
    return (
        f"Note: market data could not be fetched for these portfolio "
        f"assets: {listing}. Mention this gap in the narrative and "
        f"lower confidence accordingly; do not invent prices.\n\n"
    )


def synthesizer(state: PortfolioState) -> dict:
    """Generate the FinalReport from portfolio + market_data in State.

    Reads:
        state["portfolio"], state["market_data"]

    Returns:
        {"final_report": FinalReport}
    """
    portfolio = state["portfolio"]
    market_data = state["market_data"]

    # Any portfolio symbol absent from market_data was skipped by
    # data_ingestion (rate-limit, invalid ticker, etc.). We tell the
    # LLM explicitly so it does not invent prices for those assets.
    missing = set(portfolio.keys()) - set(market_data.keys())

    report: FinalReport = _chain.invoke(
        {
            "portfolio_table": _format_portfolio_table(portfolio),
            "market_data_table": _format_market_data_table(market_data),
            "missing_assets_block": _format_missing_assets_block(missing),
        }
    )
    return {"final_report": report}

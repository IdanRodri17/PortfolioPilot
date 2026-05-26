"""
synthesizer node — turns market data into a structured FinalReport.

This is the LLM-calling node. It builds an LCEL chain at module import
time and uses .with_structured_output(FinalReport) so the model is
constrained at sampling time to emit only valid FinalReport JSON.

Versioning:
    V1: prompt receives portfolio + market_data only. Sentiment is
        generated from the model's prior knowledge, not from grounded
        news search.
    V3: sentiment_findings and risk_analysis are injected (filled by
        upstream parallel agents).
    V5: long_term_memory is injected.
    V6: guardrail_feedback is injected on retry attempts.

The prompt template is parameterized to evolve over versions without
changing the surrounding chain wiring.
"""

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
    "User portfolio (symbol -> quantity):\n"
    "{portfolio}\n\n"
    "Latest market data (symbol -> price, change_24h_percent):\n"
    "{market_data}\n\n"
    "Produce a FinalReport for this portfolio. Compute the total "
    "valuation from the holdings and prices. Generate one MarketInsight "
    "per asset, basing sentiment on the 24h change and general knowledge "
    "of the company. Recommend rebalancing actions only if warranted — "
    "an empty list is acceptable for a single-asset portfolio. Write a "
    "2-3 paragraph summary narrative in plain prose. Self-assess "
    "confidence between 0 and 1; V1 has no news search yet, so "
    "confidence should be modest (around 0.4-0.6)."
)

# Build the prompt template + LLM chain once at module load.
_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ]
)

# gpt-4o-mini for V1 (cheap, fast, sufficient for the smoke test).
# V3 upgrades the synthesizer to gpt-4o because the prompt grows
# substantially with sentiment + risk + memory.
_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

# The chain: render prompt -> call LLM constrained to FinalReport schema.
# Invoking this chain returns a FinalReport instance directly.
_chain = _prompt | _llm.with_structured_output(FinalReport)


def synthesizer(state: PortfolioState) -> dict:
    """Generate the FinalReport from portfolio + market_data in State.

    Reads:
        state["portfolio"], state["market_data"]

    Returns:
        {"final_report": FinalReport}
    """
    report: FinalReport = _chain.invoke(
        {
            "portfolio": state["portfolio"],
            "market_data": state["market_data"],
        }
    )
    return {"final_report": report}

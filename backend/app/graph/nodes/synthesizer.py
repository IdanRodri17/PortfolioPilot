"""
synthesizer node — assembles the FinalReport from all upstream signals.

V3 changes the synthesizer's role substantially:
    V1-V2: prompt receives portfolio + market_data only. The
        synthesizer had to invent per-asset sentiment from priors.
    V3: prompt receives portfolio + market_data + sentiment_findings
        (one MarketInsight per symbol, produced by parallel sentiment_agents)
        + risk_analysis (composition + violations from risk_agent).
        The synthesizer now passes sentiment_findings through verbatim
        as market_insights, generates recommendations grounded in the
        risk violations, and writes a narrative that integrates both.

    V5: + long_term_memory injected. The synthesizer personalizes its
        recommendations and narrative using the user's remembered
        preferences — WITHOUT letting a preference override the objective
        risk analysis or fabricate facts. Reconciliation hierarchy:
        market data + risk analysis are authoritative; memory personalizes
        the framing.
    V6: + guardrail_feedback injected on retry attempts.

Why pass sentiment through verbatim:
    The upstream sentiment_agents already grounded their classification
    in Tavily news. Asking the synthesizer to re-summarize that work
    would (a) waste tokens, (b) introduce a paraphrase layer where the
    grounding could erode, (c) potentially flip sentiment if the model
    second-guesses. We tell the LLM explicitly: include these as-is.

Model:
    Upgraded to gpt-4o for V3 (per SRS §2). The prompt has grown
    substantially — sentiment_findings + risk_analysis + portfolio +
    market_data (+ long_term_memory in V5) — and the output is more
    complex (recommendations grounded in specific risk violations).
    gpt-4o-mini struggled with consistent grounding once the prompt grew
    past ~1500 tokens.
"""

from typing import Dict, List, Set

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.graph.state import PortfolioState
from app.schemas.report import FinalReport

SYSTEM_PROMPT = (
    "You are PortfolioPilot, an AI wealth-management assistant. You "
    "analyze portfolio holdings using upstream sentiment and risk "
    "analyses produced by specialist agents, and produce a structured "
    "FinalReport with per-asset insights, rebalancing recommendations, "
    "and a narrative summary. Stay grounded in the data provided — do "
    "not fabricate prices, news, or events not supported by the "
    "information given. When the user's known preferences from past "
    "sessions are provided, use them to personalize your guidance and "
    "framing, but never let a preference override the objective risk "
    "analysis, and never invent preferences that are not listed."
)

HUMAN_PROMPT = (
    "User portfolio (risk profile: {profile_name}):\n"
    "{portfolio_table}\n\n"
    "Risk profile guidance:\n"
    "{profile_description}\n\n"
    "Latest market data:\n"
    "{market_data_table}\n\n"
    "{missing_assets_block}"
    "Sentiment findings (one per portfolio asset, produced by upstream "
    "sentiment_agents grounded in real news via Tavily):\n"
    "{sentiment_findings_block}\n\n"
    "Risk analysis (deterministic, computed by upstream risk_agent):\n"
    "{risk_analysis_block}\n\n"
    "What we remember about this user from past sessions (known "
    "preferences and history — NOT new market facts to act on):\n"
    "{long_term_memory_block}\n\n"
    "Now produce the FinalReport:\n"
    "  - portfolio_valuation: compute total_usd from quantities × prices "
    "for the priced assets, and the weighted change_24h_percent.\n"
    "  - market_insights: include the upstream sentiment findings "
    "verbatim — do not rewrite, summarize, or re-classify them. Order "
    "by asset alphabetically.\n"
    "  - rebalancing_recommendations: generate concrete recommendations "
    "grounded in the risk violations above and the sentiment findings. "
    "If risk_agent flagged AAPL at 47% in a balanced profile, recommend "
    "reducing AAPL with a target_change_pct that brings it under the "
    "profile cap. If there are no violations and sentiment is uniformly "
    "stable, an empty list is correct. Where the user's remembered "
    "preferences bear on a recommendation (e.g. a stated reluctance to "
    "reduce a specific holding), reflect that in the rationale — but do "
    "NOT suppress a genuine risk violation because of a preference, and "
    "do NOT invent preferences beyond those listed above.\n"
    "  - summary_narrative: 2-3 paragraphs in plain prose integrating "
    "the sentiment picture, risk posture, and your recommendations. "
    "Where relevant, connect the analysis to the user's remembered "
    "preferences so the report feels personal and continuous with past "
    "sessions. If no preferences are on record, do not mention memory "
    "at all.\n"
    "  - confidence: V3 grounds sentiment in real Tavily news, so "
    "confidence may sit in 0.6-0.85 range. Lower it toward 0.4-0.5 if: "
    "(a) market data was missing for some assets, (b) sentiment "
    "findings were mostly Neutral with thin rationale, or (c) the "
    "report relies heavily on a sentiment_agent that returned a "
    "degraded insight (visible as 'news could not be retrieved' in the "
    "summary)."
)

_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ]
)

# gpt-4o for V3 — prompt grew substantially with sentiment + risk + the
# more nuanced recommendation logic. gpt-4o-mini was insufficiently
# grounded once the prompt passed ~1500 tokens during V3 dev.
_llm = ChatOpenAI(model=get_settings().openai_model_synthesizer, temperature=0.3)
_chain = _prompt | _llm.with_structured_output(FinalReport)


# ─── Prompt formatters ──────────────────────────────────────────────


def _format_portfolio_table(portfolio: Dict[str, float]) -> str:
    if not portfolio:
        return "(empty portfolio)"
    lines = ["| Symbol | Quantity |", "|--------|----------|"]
    for symbol, qty in portfolio.items():
        lines.append(f"| {symbol} | {qty} |")
    return "\n".join(lines)


def _format_market_data_table(market_data: Dict[str, dict]) -> str:
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
    if not missing:
        return ""
    listing = ", ".join(sorted(missing))
    return (
        f"Note: market data could not be fetched for these assets: "
        f"{listing}. Reflect this gap in the narrative and lower "
        f"confidence accordingly; do not invent prices.\n\n"
    )


def _format_sentiment_findings_block(findings: List[dict]) -> str:
    """Render sentiment_findings as a labeled list the LLM can copy verbatim.

    Sorted alphabetically so the synthesizer's market_insights output
    has stable ordering across runs (deterministic-ish demo).
    """
    if not findings:
        return "(no sentiment findings — upstream agents did not produce output)"
    sorted_findings = sorted(findings, key=lambda f: f["asset"])
    lines = []
    for f in sorted_findings:
        lines.append(f"- {f['asset']} — {f['sentiment']}: {f['summary']}")
    return "\n".join(lines)


def _format_risk_analysis_block(risk: dict) -> str:
    """Render the risk_analysis dict as a readable bullet block.

    Composition is sorted descending so the largest holdings are
    visually first — the LLM should weight rebalancing recommendations
    toward the top of that list.
    """
    composition_lines = [
        f"  - {sym}: {pct}%"
        for sym, pct in sorted(
            risk["composition_pct"].items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
    ]
    composition_block = (
        "\n".join(composition_lines) if composition_lines else "  (none priced)"
    )

    violations = risk["violations"]
    if violations:
        violations_block = "\n".join(f"  {i}. {v}" for i, v in enumerate(violations, 1))
    else:
        violations_block = "  (none — composition is within profile thresholds)"

    return (
        f"- Total portfolio value: ${risk['total_value_usd']}\n"
        f"- Composition (largest first):\n{composition_block}\n"
        f"- Violations vs profile thresholds:\n{violations_block}"
    )


def _format_long_term_memory_block(memories: List[dict]) -> str:
    """Render retrieved long-term memories as a labeled list for the prompt.

    Each memory is a stored value dict from PostgresStore, shaped at
    minimum as {"insight": str} and optionally carrying a "context"
    string (added by memory_extractor in step 5). memory_loader returns
    them most-relevant-first, so the order here already reflects semantic
    relevance to the current portfolio.

    Returns an explicit "nothing on record" sentinel when empty — the
    prompt instructs the model to stay silent about memory in that case,
    so first-run reports don't awkwardly reference an empty history.
    """
    if not memories:
        return "(no past insights on record for this user yet)"
    lines = []
    for m in memories:
        insight = m.get("insight")
        if not insight:
            continue
        context = m.get("context")
        lines.append(f"- {insight} ({context})" if context else f"- {insight}")
    return (
        "\n".join(lines) if lines else "(no past insights on record for this user yet)"
    )


def synthesizer(state: PortfolioState) -> dict:
    """Assemble the FinalReport from all merged upstream signals.

    Reads:
        portfolio, market_data, sentiment_findings (reducer-merged),
        risk_analysis, risk_profile, long_term_memory (V5).

    Returns:
        {"final_report": FinalReport}
    """
    portfolio = state["portfolio"]
    market_data = state["market_data"]
    sentiment_findings = state.get("sentiment_findings", [])
    risk_analysis = state["risk_analysis"]
    risk_profile = state["risk_profile"]
    long_term_memory = state.get("long_term_memory", [])

    missing = set(portfolio.keys()) - set(market_data.keys())

    report: FinalReport = _chain.invoke(
        {
            "profile_name": risk_profile,
            "profile_description": risk_analysis.get("profile_description", ""),
            "portfolio_table": _format_portfolio_table(portfolio),
            "market_data_table": _format_market_data_table(market_data),
            "missing_assets_block": _format_missing_assets_block(missing),
            "sentiment_findings_block": _format_sentiment_findings_block(
                sentiment_findings
            ),
            "risk_analysis_block": _format_risk_analysis_block(risk_analysis),
            "long_term_memory_block": _format_long_term_memory_block(long_term_memory),
        }
    )
    return {"final_report": report}

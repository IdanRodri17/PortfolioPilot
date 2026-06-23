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
from app.schemas.report import (
    AssetAllocation,
    FinalReport,
    ReportBody,
    SectorAllocation,
    SectorConcentration,
)
from app.tools.stock_data import is_tase

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
    "{guardrail_feedback_block}"
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
    "Sector concentration (deterministic, computed by upstream "
    "macro_context_agent over the whole portfolio):\n"
    "{macro_analysis_block}\n\n"
    "{israeli_context_block}"
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
    "do NOT invent preferences beyond those listed above. When the macro "
    "analysis flags high sector concentration, you may factor trimming the "
    "dominant sector into the rationale — without inventing numbers.\n"
    "  - summary_narrative: 2-3 paragraphs in plain prose integrating "
    "the sentiment picture, risk posture, sector concentration, and your "
    "recommendations. When the macro analysis flags a dominant sector or "
    "elevated concentration, name the sector and what it means for "
    "diversification, using the figures above rather than invented ones. "
    "If Israeli market context is provided above (TASE holdings or the Bank of "
    "Israel rate), weave it in briefly. "
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
# Bind the LLM to ReportBody, NOT FinalReport: the model fills the authored
# fields, and the synthesizer node attaches the deterministic
# portfolio_composition afterwards (V10a) so exact allocation percentages
# never pass through the LLM.
_chain = _prompt | _llm.with_structured_output(ReportBody)


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


def _format_macro_block(macro: dict) -> str:
    """Render macro_analysis as a readable block, mirroring the risk block.

    Passed to the LLM verbatim so it can narrate the concentration without
    re-deriving the numbers — the values are deterministic; the model only
    narrates them.
    """
    breakdown = macro.get("sector_breakdown") if macro else None
    if not breakdown:
        return "  (sector concentration unavailable — no priced holdings)"
    sector_lines = "\n".join(
        f"  - {sector}: {pct}%" for sector, pct in breakdown.items()
    )
    return (
        f"- Dominant sector: {macro.get('dominant_sector')}\n"
        f"- Concentration: {macro.get('concentration')} "
        f"(diversification score {macro.get('diversification_score')} / 1.0)\n"
        f"- Sector breakdown (largest first):\n{sector_lines}\n"
        f"- Summary: {macro.get('note', '')}"
    )


def _format_israeli_context_block(portfolio: Dict[str, float], boi_rate) -> str:
    """Israeli-market context (V16): TASE holdings + the Bank of Israel rate.

    Self-contained block — empty string when there's nothing to say (no TASE
    holding and no configured rate), so the prompt slot simply disappears.
    """
    tase = sorted(s for s in portfolio if is_tase(s))
    if not tase and boi_rate is None:
        return ""
    lines = []
    if tase:
        lines.append(f"TASE-listed (Tel Aviv) holdings: {', '.join(tase)}.")
    if boi_rate is not None:
        lines.append(f"Bank of Israel policy rate: {boi_rate}%.")
    body = "\n".join(f"  - {line}" for line in lines)
    return f"Israeli market context:\n{body}\n\n"


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


def _build_composition(risk_analysis: dict) -> List[AssetAllocation]:
    """Build the value-weighted allocation deterministically (V10a).

    risk_agent already computed `composition_pct` ({symbol: percent}) and
    `total_value_usd` in Python. We derive each asset's dollar value as
    pct/100 * total — the numbers never route through the LLM. Sorted
    largest-first so the donut's first slice is the biggest holding. An
    empty composition (no priced assets) yields [].
    """
    composition_pct: Dict[str, float] = risk_analysis.get("composition_pct", {})
    total_value_usd: float = risk_analysis.get("total_value_usd", 0.0)
    return [
        AssetAllocation(
            asset=symbol,
            pct=pct,
            value_usd=round(pct / 100 * total_value_usd, 2),
            currency="ILS" if is_tase(symbol) else "USD",
        )
        for symbol, pct in sorted(
            composition_pct.items(), key=lambda kv: kv[1], reverse=True
        )
    ]


def _build_sector_concentration(macro: dict) -> SectorConcentration | None:
    """Build the deterministic sector-concentration block from macro_analysis.

    Returns None when the macro agent produced nothing usable, so the report
    omits the section (and reports archived before V11 stay None).
    """
    if not macro or not macro.get("sector_breakdown"):
        return None
    breakdown = macro["sector_breakdown"]  # {sector: pct}, largest first
    return SectorConcentration(
        sectors=[SectorAllocation(sector=s, pct=p) for s, p in breakdown.items()],
        dominant_sector=macro.get("dominant_sector"),
        concentration=macro.get("concentration", "unknown"),
        diversification_score=macro.get("diversification_score", 0.0),
        note=macro.get("note", ""),
    )


def _format_guardrail_feedback_block(feedback: str | None) -> str:
    """Reflexion preamble injected only on a guardrail retry."""
    if not feedback:
        return ""
    return (
        "PREVIOUS ATTEMPT FAILED VALIDATION. Reasons:\n"
        f"{feedback}\n\n"
        "Regenerate the report addressing these specific issues. Stay strictly "
        "grounded in the data provided below; do not invent prices, news, or "
        "preferences.\n\n"
    )


def synthesizer(state: PortfolioState) -> dict:
    """Assemble the FinalReport from all merged upstream signals.

    Reads:
        portfolio, market_data, sentiment_findings (reducer-merged),
        risk_analysis, risk_profile, long_term_memory (V5).

    Returns:
        {"final_report": FinalReport}

    The LLM authors the ReportBody; the deterministic value-weighted
    portfolio_composition is attached here (V10a) from risk_analysis.
    """
    portfolio = state["portfolio"]
    market_data = state["market_data"]
    sentiment_findings = state.get("sentiment_findings", [])
    risk_analysis = state["risk_analysis"]
    macro_analysis = state.get("macro_analysis", {})
    risk_profile = state["risk_profile"]
    long_term_memory = state.get("long_term_memory", [])

    missing = set(portfolio.keys()) - set(market_data.keys())

    body: ReportBody = _chain.invoke(
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
            "macro_analysis_block": _format_macro_block(macro_analysis),
            "israeli_context_block": _format_israeli_context_block(
                portfolio, get_settings().bank_of_israel_rate
            ),
            "long_term_memory_block": _format_long_term_memory_block(long_term_memory),
            "guardrail_feedback_block": _format_guardrail_feedback_block(
                state.get("guardrail_feedback")
            ),
        }
    )

    report = FinalReport(
        **body.model_dump(),
        portfolio_composition=_build_composition(risk_analysis),
        sector_concentration=_build_sector_concentration(macro_analysis),
    )
    return {"final_report": report}

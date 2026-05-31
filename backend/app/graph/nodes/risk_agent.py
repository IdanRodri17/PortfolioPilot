"""
risk_agent — deterministic portfolio composition analysis.

Single-instance node (NOT Send-fanned). Reads the whole portfolio +
market_data + risk_profile, computes each asset's percentage of total
value, checks against RISK_PROFILES thresholds, and emits a structured
risk_analysis dict for the synthesizer to weave into the report.

Contrast with sentiment_agent:
    sentiment_agent runs N times (once per symbol) via Send() fan-out.
    Reads state["symbol"] singular. Returns single-item list to a
    reducer-merged State field.

    risk_agent runs once. Reads the whole portfolio. Returns a dict to
    a single-writer State field (no reducer needed).

Why pure compute (no LLM):
    Percentages are arithmetic — LLMs are unreliable at it, and the
    cost (an extra round-trip per report) buys nothing the synthesizer
    cannot do itself. By computing facts deterministically here and
    letting the synthesizer write prose from them, we get:
        - Cheaper reports (one fewer LLM call).
        - Faster reports (no extra network hop per generation).
        - Deterministic numbers the V6 guardrail can rule-check.

Versioning:
    V3: stock-only. The max_crypto_pct threshold in RISK_PROFILES is
        defined but not evaluated — V3 has no crypto symbol detector.
    V6.5: add crypto detection (CoinGecko symbols vs yfinance symbols)
          and activate the crypto threshold check.
"""

import logging
from typing import Dict

from app.graph.risk_profiles import RISK_PROFILES
from app.graph.state import PortfolioState

logger = logging.getLogger(__name__)


def _compute_composition(
    portfolio: Dict[str, float],
    market_data: Dict[str, dict],
) -> tuple[float, Dict[str, float]]:
    """Compute total portfolio value and per-asset percentage shares.

    Only assets with both a quantity (portfolio) and a price (market_data)
    are included. Symbols missing from market_data — skipped by
    data_ingestion's per-asset error tolerance (V2) — are ignored here
    too. The synthesizer prompt already notes the gap.

    Returns:
        (total_usd, {symbol: percent_of_total}).
        Empty dict and 0.0 total if no assets have market data.
    """
    priced = {
        symbol: qty * market_data[symbol]["price"]
        for symbol, qty in portfolio.items()
        if symbol in market_data
    }
    total = sum(priced.values())
    if total == 0:
        return 0.0, {}
    composition = {symbol: (value / total) * 100 for symbol, value in priced.items()}
    return total, composition


def _check_violations(
    composition: Dict[str, float],
    portfolio_size: int,
    profile_thresholds: dict,
    profile_name: str,
) -> list[str]:
    """Return a list of concrete violation strings vs the profile thresholds.

    Each entry is a complete human-readable sentence the synthesizer can
    quote into the narrative without rephrasing the numbers.
    """
    violations = []

    # Single-asset concentration check.
    max_pct = profile_thresholds["max_single_asset_pct"]
    for symbol, pct in composition.items():
        if pct > max_pct:
            violations.append(
                f"{symbol} is {pct:.1f}% of the portfolio, exceeding the "
                f"{profile_name} profile cap of {max_pct:.0f}%."
            )

    # Diversification check — only meaningful when we have priced assets.
    min_assets = profile_thresholds["min_assets_recommended"]
    if portfolio_size > 0 and portfolio_size < min_assets:
        violations.append(
            f"Portfolio holds {portfolio_size} asset(s); the {profile_name} "
            f"profile recommends at least {min_assets} for adequate diversification."
        )

    # max_crypto_pct intentionally not evaluated in V3 — no crypto
    # symbol detector yet. V6.5 will add this.

    return violations


def risk_agent(state: PortfolioState) -> dict:
    """Analyze portfolio composition against the user's risk profile.

    Reads:
        state["portfolio"], state["market_data"], state["risk_profile"]

    Returns:
        {"risk_analysis": {
            "profile": str,
            "profile_description": str,
            "total_value_usd": float,
            "composition_pct": {symbol: percent},
            "violations": [str, ...],
        }}

    Defensive: if market_data is empty (every yfinance call failed),
    returns an analysis with an explicit "data unavailable" violation
    so the synthesizer doesn't try to narrate around silent emptiness.
    """
    portfolio = state["portfolio"]
    market_data = state["market_data"]
    profile_name = state["risk_profile"]
    profile = RISK_PROFILES[profile_name]

    total, composition = _compute_composition(portfolio, market_data)

    if not composition:
        # Edge case: portfolio is non-empty but no symbol had market data.
        logger.warning(
            "risk_agent: no priced assets for risk analysis "
            "(portfolio=%d symbols, market_data=%d symbols)",
            len(portfolio),
            len(market_data),
        )
        return {
            "risk_analysis": {
                "profile": profile_name,
                "profile_description": profile["description"],
                "total_value_usd": 0.0,
                "composition_pct": {},
                "violations": [
                    "Risk analysis could not be performed — market data "
                    "was unavailable for every asset in the portfolio."
                ],
            }
        }

    violations = _check_violations(
        composition=composition,
        portfolio_size=len(composition),
        profile_thresholds=profile,
        profile_name=profile_name,
    )

    return {
        "risk_analysis": {
            "profile": profile_name,
            "profile_description": profile["description"],
            "total_value_usd": round(total, 2),
            "composition_pct": {sym: round(pct, 2) for sym, pct in composition.items()},
            "violations": violations,
        }
    }

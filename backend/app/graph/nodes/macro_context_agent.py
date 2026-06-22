"""
macro_context_agent — deterministic sector-concentration analysis (V11).

Looks at the portfolio *as a whole* and flags correlated concentration the
per-asset sentiment agents can't see — e.g. "78% of your value is in
Technology; that's not diversified, it's one sector bet."

Shape mirrors risk_agent, NOT sentiment_agent:
    Single-instance node (NOT Send-fanned per symbol). Runs once over the whole
    portfolio, reading portfolio + market_data, and writes the single-writer
    state field `macro_analysis` (no reducer needed).

Why it can't read risk_analysis:
    It is fanned out in PARALLEL with risk_agent from data_ingestion, so
    risk_analysis isn't available yet. It computes its own value weights from
    portfolio + market_data (same basis as risk_agent) and aggregates them by
    each asset's sector.

Why pure compute (no LLM):
    Sector shares and the concentration index are arithmetic. We compute the
    facts here deterministically and let the synthesizer narrate them — cheaper,
    faster, and rule-checkable, consistent with risk_agent.
"""

import logging
from typing import Dict, Tuple

from app.graph.state import PortfolioState
from app.tools.stock_data import get_sector

logger = logging.getLogger(__name__)

# A single sector above this share of value is "high" concentration; above the
# moderate cut it's "moderate"; otherwise "low".
_HIGH_CONCENTRATION_PCT = 60.0
_MODERATE_CONCENTRATION_PCT = 40.0


def _compute_sector_shares(
    portfolio: Dict[str, float],
    market_data: Dict[str, dict],
) -> Tuple[Dict[str, float], float]:
    """Value-weighted sector shares (percent) over the priced holdings.

    Only assets with both a quantity and a price are counted (same basis as
    risk_agent). Each symbol's value is bucketed by its sector.

    Returns:
        ({sector: percent_of_total}, total_priced_usd). Empty dict + 0.0 if no
        asset could be priced.
    """
    sector_values: Dict[str, float] = {}
    total = 0.0
    for symbol, qty in portfolio.items():
        if symbol not in market_data:
            continue
        value = qty * market_data[symbol]["price"]
        if value <= 0:
            continue
        sector = get_sector(symbol)
        sector_values[sector] = sector_values.get(sector, 0.0) + value
        total += value

    if total == 0:
        return {}, 0.0
    shares = {sector: (value / total) * 100 for sector, value in sector_values.items()}
    return shares, total


def _build_note(
    dominant_sector: str,
    dominant_pct: float,
    concentration: str,
    sector_count: int,
) -> str:
    """A complete sentence the synthesizer can quote without re-deriving numbers."""
    if concentration == "high":
        return (
            f"{dominant_sector} makes up {dominant_pct:.1f}% of portfolio value — "
            f"concentration is high; the portfolio is largely a single-sector bet."
        )
    if concentration == "moderate":
        return (
            f"{dominant_sector} is the largest sector at {dominant_pct:.1f}% of value "
            f"across {sector_count} sectors — moderate concentration."
        )
    return (
        f"Value is spread across {sector_count} sectors with no single sector above "
        f"{dominant_pct:.1f}% — the portfolio is well diversified by sector."
    )


def macro_context_agent(state: PortfolioState) -> dict:
    """Assess value-weighted sector concentration across the whole portfolio.

    Reads:
        state["portfolio"], state["market_data"]

    Returns:
        {"macro_analysis": {
            "sector_breakdown": {sector: percent},   # largest first
            "dominant_sector": str | None,
            "concentration": "high" | "moderate" | "low" | "unknown",
            "diversification_score": float,           # 0..1, 1 = most diverse
            "note": str,
        }}

    Defensive: if nothing could be priced, returns an explicit "unknown" state
    so the synthesizer doesn't narrate around silent emptiness.
    """
    portfolio = state["portfolio"]
    market_data = state["market_data"]

    shares, _total = _compute_sector_shares(portfolio, market_data)

    if not shares:
        logger.warning(
            "macro_context_agent: no priced assets for sector analysis "
            "(portfolio=%d symbols, market_data=%d symbols)",
            len(portfolio),
            len(market_data),
        )
        return {
            "macro_analysis": {
                "sector_breakdown": {},
                "dominant_sector": None,
                "concentration": "unknown",
                "diversification_score": 0.0,
                "note": "Sector concentration could not be assessed — no priced holdings.",
            }
        }

    # Sort largest-first so the breakdown and the dominant sector read naturally.
    ordered = dict(sorted(shares.items(), key=lambda kv: kv[1], reverse=True))
    dominant_sector, dominant_pct = next(iter(ordered.items()))

    # Herfindahl-Hirschman index over sector fractions; diversification = 1 - HHI.
    # 0 for a single sector, approaching 1 as value spreads across many sectors.
    hhi = sum((pct / 100) ** 2 for pct in ordered.values())
    diversification_score = round(1 - hhi, 3)

    if dominant_pct >= _HIGH_CONCENTRATION_PCT:
        concentration = "high"
    elif dominant_pct >= _MODERATE_CONCENTRATION_PCT:
        concentration = "moderate"
    else:
        concentration = "low"

    return {
        "macro_analysis": {
            "sector_breakdown": {s: round(p, 2) for s, p in ordered.items()},
            "dominant_sector": dominant_sector,
            "concentration": concentration,
            "diversification_score": diversification_score,
            "note": _build_note(
                dominant_sector, dominant_pct, concentration, len(ordered)
            ),
        }
    }

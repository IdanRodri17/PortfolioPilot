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
    V16: crypto detection (CoinGecko symbols, via is_crypto) activates the
         max_crypto_pct threshold check.
"""

import logging
import math
from typing import Dict

from app.graph.risk_profiles import RISK_PROFILES
from app.graph.state import PortfolioState
from app.tools.stock_data import is_crypto, is_tase, usd_ils_rate

logger = logging.getLogger(__name__)


def _compute_pnl(
    portfolio: Dict[str, float],
    cost_basis: Dict[str, float],
    market_data: Dict[str, dict],
) -> tuple[Dict[str, dict], dict | None]:
    """Per-asset and total gain/loss vs cost basis, in USD-canonical (V20).

    Buy prices are stored in the symbol's NATIVE currency (ILS for TASE, USD
    otherwise) — exactly what the editor shows and the user types. Current prices
    from data_ingestion are already USD-normalized, so we convert each native buy
    price to USD before comparing. Because both the buy and current price are
    divided by the same ILS rate, the percentage is FX-independent (the asset's
    own return); the absolute gain is expressed in current USD.

    Only symbols with a quantity, a current price, AND a positive buy price are
    included. Returns ({} , None) when nothing is trackable.
    """
    if not cost_basis:
        return {}, None

    positions: Dict[str, dict] = {}
    rate: float | None = None
    total_cost = 0.0
    total_value = 0.0

    for symbol, qty in portfolio.items():
        buy_native = cost_basis.get(symbol)
        md = market_data.get(symbol)
        if md is None or not buy_native or not math.isfinite(buy_native) or buy_native <= 0:
            continue
        current_usd = md["price"]
        # NaN is truthy and NaN<=0 is False, so isfinite() is the real guard
        # against a corrupt/incomplete price reaching the P/L math.
        if not math.isfinite(current_usd) or current_usd <= 0:
            continue
        if is_tase(symbol):
            if rate is None:
                rate = usd_ils_rate()
            buy_usd = buy_native / rate
        else:
            buy_usd = buy_native
        if not math.isfinite(buy_usd) or buy_usd <= 0:
            continue
        cost_usd = buy_usd * qty
        value_usd = current_usd * qty
        positions[symbol] = {
            "cost_basis_usd": round(cost_usd, 2),
            "gain_loss_usd": round(value_usd - cost_usd, 2),
            "gain_loss_pct": round((current_usd - buy_usd) / buy_usd * 100, 2),
        }
        total_cost += cost_usd
        total_value += value_usd

    if not positions or total_cost <= 0:
        return {}, None

    totals = {
        "total_cost_basis_usd": round(total_cost, 2),
        "total_gain_loss_usd": round(total_value - total_cost, 2),
        "total_gain_loss_pct": round((total_value - total_cost) / total_cost * 100, 2),
    }
    return positions, totals


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

    # Crypto-exposure check (activated in V16). Sum the value share of crypto
    # holdings and flag if it exceeds the profile's max_crypto_pct.
    max_crypto = profile_thresholds["max_crypto_pct"]
    crypto_pct = sum(pct for sym, pct in composition.items() if is_crypto(sym))
    if crypto_pct > max_crypto:
        violations.append(
            f"Crypto is {crypto_pct:.1f}% of the portfolio, exceeding the "
            f"{profile_name} profile cap of {max_crypto:.0f}%."
        )

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
                "total_change_24h_percent": 0.0,
                "positions": {},
                "pnl_totals": None,
            }
        }

    violations = _check_violations(
        composition=composition,
        portfolio_size=len(composition),
        profile_thresholds=profile,
        profile_name=profile_name,
    )

    # V20: deterministic gain/loss vs cost basis (only for held buy prices).
    positions, pnl_totals = _compute_pnl(
        portfolio, state.get("cost_basis", {}) or {}, market_data
    )

    # V21: value-weighted 24h change, computed deterministically here so the
    # report's HEADLINE valuation never relies on LLM arithmetic. Only priced
    # assets contribute; matches the total used for composition.
    weighted_change = 0.0
    if total > 0:
        weighted_change = (
            sum(
                portfolio[sym]
                * market_data[sym]["price"]
                * (market_data[sym].get("change_24h_percent") or 0.0)
                for sym in portfolio
                if sym in market_data
            )
            / total
        )

    return {
        "risk_analysis": {
            "profile": profile_name,
            "profile_description": profile["description"],
            "total_value_usd": round(total, 2),
            "total_change_24h_percent": round(weighted_change, 2),
            "composition_pct": {sym: round(pct, 2) for sym, pct in composition.items()},
            "violations": violations,
            "positions": positions,
            "pnl_totals": pnl_totals,
        }
    }

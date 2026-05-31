"""
Risk profile thresholds for the V3 risk_agent.

Each profile defines numeric thresholds the risk_agent compares the
user's actual portfolio composition against. Violations become
observations the risk_agent reports back to the synthesizer.

These are heuristics, not financial advice. They exist to give the
risk_agent concrete numbers to ground its analysis rather than asking
the LLM to invent its own framework on every call.

Versioning:
    V3: stock-only thresholds (max_single_asset_pct, min_assets_recommended).
    V6.5: max_crypto_pct becomes active once CoinGecko + a crypto-symbol
          detector land. The threshold is defined now so V6.5 is a code-
          only change in risk_agent, not a config + code change.
"""

from typing import Any, Dict

RISK_PROFILES: Dict[str, Dict[str, Any]] = {
    "conservative": {
        "description": (
            "Capital preservation focused. Tolerates limited volatility, "
            "favors diversification, avoids concentration in any single asset."
        ),
        "max_single_asset_pct": 25.0,
        "max_crypto_pct": 10.0,  # active in V6.5
        "min_assets_recommended": 5,
    },
    "balanced": {
        "description": (
            "Mix of growth and capital preservation. Moderate concentration "
            "and moderate crypto exposure acceptable."
        ),
        "max_single_asset_pct": 35.0,
        "max_crypto_pct": 25.0,  # active in V6.5
        "min_assets_recommended": 4,
    },
    "aggressive": {
        "description": (
            "Growth focused. High tolerance for volatility and concentration; "
            "willing to overweight specific bets."
        ),
        "max_single_asset_pct": 50.0,
        "max_crypto_pct": 50.0,  # active in V6.5
        "min_assets_recommended": 3,
    },
}

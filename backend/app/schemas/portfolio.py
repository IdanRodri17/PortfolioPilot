"""
Pydantic models for portfolio CRUD endpoints.

These models are the API boundary contracts — they validate inbound JSON
and shape outbound responses. They are deliberately decoupled from the
SQLAlchemy models: the wire format denormalizes risk_profile (lives on
User) and assets (lives on Portfolio) into one client-friendly object.

Versioning:
    V2: PortfolioRequest / PortfolioResponse with stock symbols.
    V6.5: no schema change — crypto symbols are valid keys in the
          open `assets` dict.
"""

from datetime import datetime
from typing import Dict, List, Literal

from pydantic import BaseModel, Field, field_validator

# Reused in api/portfolio.py and in the synthesizer prompt later.
RiskProfile = Literal["conservative", "balanced", "aggressive"]


class PortfolioRequest(BaseModel):
    """Inbound payload for POST /api/portfolio.

    Acts as create-or-replace: user_id is the key, and resubmitting
    fully overwrites the prior assets map.
    """

    user_id: str = Field(
        min_length=1,
        description="Stable user identifier, e.g. 'idan_demo'.",
    )
    assets: Dict[str, float] = Field(
        description="Asset map: symbol → quantity. e.g. {'AAPL': 10, 'BTC': 0.5}.",
    )
    cost_basis: Dict[str, float] = Field(
        default_factory=dict,
        description="Optional per-symbol buy price (cost basis) in the symbol's "
        "native currency (USD, or ILS for TASE), for gain/loss. e.g. {'AAPL': 150}.",
    )
    risk_profile: RiskProfile = Field(
        description="User's risk tolerance — shapes the V3 risk_agent thresholds."
    )

    @field_validator("assets")
    @classmethod
    def _validate_quantities(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Quantities must be positive — a 'zero AAPL' holding is a
        missing key, not an explicit value of 0."""
        for symbol, qty in v.items():
            if qty <= 0:
                raise ValueError(f"Quantity for '{symbol}' must be > 0 (got {qty}).")
        return v

    @field_validator("cost_basis")
    @classmethod
    def _validate_cost_basis(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Buy prices, when given, must be positive. cost_basis is optional and
        per-symbol — a holding without a buy price simply isn't tracked for P/L."""
        for symbol, price in v.items():
            if price <= 0:
                raise ValueError(f"Buy price for '{symbol}' must be > 0 (got {price}).")
        return v


class WatchlistRequest(BaseModel):
    """Inbound payload for PUT /api/watchlist/{user_id} (V25) — full-replace list
    of tickers the user tracks but doesn't own."""

    symbols: List[str] = Field(
        default_factory=list, description="Tickers to watch, e.g. ['NVDA', 'META']."
    )

    @field_validator("symbols")
    @classmethod
    def _normalize(cls, v: List[str]) -> List[str]:
        """Upper-case, trim, drop blanks/dupes; cap the list to keep it sane."""
        out: List[str] = []
        for s in v:
            sym = s.strip().upper()
            if sym and sym not in out:
                out.append(sym)
        if len(out) > 30:
            raise ValueError("Watchlist is limited to 30 symbols.")
        return out


class PortfolioResponse(BaseModel):
    """Outbound payload for both POST and GET /api/portfolio routes.

    Denormalizes across User.risk_profile and Portfolio.assets so the
    client never has to make two requests to render a portfolio view.
    """

    user_id: str
    assets: Dict[str, float]
    cost_basis: Dict[str, float] = Field(default_factory=dict)
    risk_profile: RiskProfile
    updated_at: datetime = Field(
        description="When the portfolio row was last written (server-side timestamp)."
    )

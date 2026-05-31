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
from typing import Dict, Literal

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


class PortfolioResponse(BaseModel):
    """Outbound payload for both POST and GET /api/portfolio routes.

    Denormalizes across User.risk_profile and Portfolio.assets so the
    client never has to make two requests to render a portfolio view.
    """

    user_id: str
    assets: Dict[str, float]
    risk_profile: RiskProfile
    updated_at: datetime = Field(
        description="When the portfolio row was last written (server-side timestamp)."
    )

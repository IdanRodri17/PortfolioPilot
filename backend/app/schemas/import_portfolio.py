"""
Pydantic contracts for portfolio import (V26).

The import endpoint is a *dry-run parser*: it turns a CSV blob or a free-text
paste into a reviewable list of holdings. It never writes — the only writer
stays POST /api/portfolio. So these models describe the parse REQUEST and the
PREVIEW the frontend renders for the user to edit before saving.

Kept in its own module (not schemas/portfolio.py) because it's a separate,
additive concern; nothing here changes the existing portfolio contracts.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Which parser to run. The frontend tab the user picked is authoritative; we
# don't auto-detect server-side.
ImportMode = Literal["csv", "text"]

# Per-mode input caps — bound cost/abuse before any work happens (CSV parse is
# cheap, but the text path spends OpenAI tokens). Over-cap -> 422.
_TEXT_MAX_CHARS = 4_000
_TEXT_MAX_LINES = 60
_CSV_MAX_CHARS = 200_000
_CSV_MAX_LINES = 1_000

# A single review row's resolution status. Drives the preview's colors and
# whether that row blocks save (mirrors the editor's typo-vs-outage split).
RowStatus = Literal["ok", "unknown", "unverified", "needs_quantity", "duplicate"]


class ImportRequest(BaseModel):
    """Inbound payload for POST /api/portfolio/parse."""

    user_id: str = Field(min_length=1, description="Owner of the portfolio.")
    mode: ImportMode = Field(description="'csv' (deterministic) or 'text' (one LLM call).")
    content: str = Field(min_length=1, description="The pasted CSV or free-text holdings.")

    @model_validator(mode="after")
    def _enforce_caps(self) -> "ImportRequest":
        chars = len(self.content)
        lines = self.content.count("\n") + 1
        if self.mode == "text":
            if chars > _TEXT_MAX_CHARS:
                raise ValueError(
                    f"Text is too long ({chars} chars); limit is {_TEXT_MAX_CHARS}."
                )
            if lines > _TEXT_MAX_LINES:
                raise ValueError(
                    f"Too many lines ({lines}); limit is {_TEXT_MAX_LINES} for free text."
                )
        else:  # csv
            if chars > _CSV_MAX_CHARS:
                raise ValueError(
                    f"CSV is too large ({chars} chars); limit is {_CSV_MAX_CHARS}."
                )
            if lines > _CSV_MAX_LINES:
                raise ValueError(
                    f"Too many rows ({lines}); limit is {_CSV_MAX_LINES}."
                )
        return self


class PreviewRow(BaseModel):
    """One parsed holding, resolved against live market data, for the user to
    review. `input_symbol` preserves the verbatim token the user typed (e.g.
    "Apple") so an unresolved row stays recognizable and fixable."""

    symbol: str
    input_symbol: str
    quantity: Optional[float] = None
    cost_basis: Optional[float] = None  # native currency, echoed unchanged
    status: RowStatus
    name: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None  # from the validated lookup ONLY, never inferred
    note: Optional[str] = None
    line: Optional[int] = None  # source CSV line, for the "couldn't read" panel


class RowError(BaseModel):
    """A CSV line we couldn't turn into a holding — surfaced, never dropped."""

    line: Optional[int] = None
    raw: str
    reason: str


class ImportPreview(BaseModel):
    """Outbound payload for POST /api/portfolio/parse — the reviewable result."""

    mode: str
    rows: List[PreviewRow] = Field(default_factory=list)
    errors: List[RowError] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    truncated: bool = False
    # Set only when the whole parse failed (e.g. the LLM was unreachable); the
    # handler returns a 200 with this set rather than a 500.
    parse_error: Optional[str] = None

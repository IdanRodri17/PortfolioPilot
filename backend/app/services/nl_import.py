"""
Natural-language holdings parser (V26) — the only new LLM surface.

One structured ChatOpenAI call turns free text like
    "10 Apple, 0.5 BTC, 1000 TEVA bought at 12"
into intermediate holding dicts that converge with the CSV parser's output, so
both modes flow through the same `validate_holdings`.

It lives in `services/`, NOT `app/graph/`, so graph purity holds — this is
boundary parsing, never a graph node. The LLM does extraction + name->ticker
resolution ONLY; it never decides whether a ticker is valid (lookup_symbol does)
and never assigns a currency (the validated lookup does). It is explicitly told
not to invent tickers.

The chain matches the codebase pattern exactly:
    _chain = _prompt | _llm.with_structured_output(_ExtractedHoldings)
(same as synthesizer.py / guardrail.py). Temperature 0 for a deterministic,
extraction-only task.
"""

from __future__ import annotations

from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings


# Wall-clock budget for the extraction call. Set as the client's transport
# timeout (with retries off) so the underlying HTTP request actually aborts —
# otherwise asyncio.wait_for in the handler only stops awaiting and orphans the
# worker thread while the SDK keeps retrying for its (long) default duration.
LLM_TIMEOUT_SECONDS = 20.0


class NLParseError(Exception):
    """The LLM extraction failed (provider error, bad output). The handler turns
    this into a clean parse_error in the preview — never a 500."""


class _ExtractedHolding(BaseModel):
    symbol: str = Field(
        description=(
            "The STOCK TICKER or crypto symbol for this holding, uppercase. "
            "Resolve a company name to its ticker (Apple -> AAPL, Microsoft -> "
            "MSFT, Bitcoin -> BTC, Tesla -> TSLA). Tel Aviv Stock Exchange "
            "listings use the .TA suffix (Teva -> TEVA.TA, Bank Leumi -> LUMI.TA). "
            "If you cannot confidently determine a ticker, copy the exact word the "
            "user wrote instead — do NOT invent a plausible-looking ticker."
        )
    )
    name_or_token: str = Field(
        description="The exact word(s) the user typed for this holding, e.g. 'Apple' or 'AAPL'."
    )
    quantity: Optional[float] = Field(
        default=None,
        description="Number of units/shares held, or null if the text doesn't state one.",
    )
    cost_basis: Optional[float] = Field(
        default=None,
        description=(
            "Per-unit buy price ONLY if the text explicitly says bought/purchased/"
            "at/for a price (e.g. 'bought at 12' -> 12). Otherwise null. Never guess."
        ),
    )


class _ExtractedHoldings(BaseModel):
    holdings: List[_ExtractedHolding] = Field(default_factory=list)


_SYSTEM_PROMPT = (
    "You extract a list of investment holdings from a user's free-text description "
    "of their portfolio. Return one entry per distinct holding. Map company names "
    "to their exchange tickers, but never invent a ticker you aren't confident "
    "about — copy the user's word verbatim instead. Extract a quantity and a "
    "per-unit buy price only when the text actually states them; otherwise leave "
    "them null. Do not add holdings the user didn't mention."
)
_HUMAN_PROMPT = "Extract the holdings from this text:\n\n{text}"

_prompt = ChatPromptTemplate.from_messages(
    [("system", _SYSTEM_PROMPT), ("human", _HUMAN_PROMPT)]
)

# Lazily built on first use (same chain shape as synthesizer.py:
# _prompt | _llm.with_structured_output(...)). Lazy rather than module-level so
# importing this module — which the app does at boot and the test suite does to
# exercise parse_text with a faked chain — never requires an OpenAI key, and the
# CSV-only path never constructs the client.
_chain = None


def _get_chain():
    global _chain
    if _chain is None:
        _llm = ChatOpenAI(
            model=get_settings().openai_model_synthesizer,
            temperature=0,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        _chain = _prompt | _llm.with_structured_output(_ExtractedHoldings)
    return _chain


def parse_text(content: str) -> List[dict]:
    """Run the one LLM extraction call and return intermediate holding dicts in
    the SAME shape parse_csv produces. Raises NLParseError on any failure so the
    caller returns a clean parse_error rather than a 500.

    This is a blocking call; the API handler wraps it in asyncio.to_thread under
    a wall-clock timeout so a hung provider can't pin a request.
    """
    try:
        result: _ExtractedHoldings = _get_chain().invoke({"text": content})
    except Exception as exc:  # noqa: BLE001 — any LLM/transport failure -> clean error
        raise NLParseError(str(exc)) from exc

    rows: List[dict] = []
    for h in result.holdings:
        symbol = (h.symbol or h.name_or_token or "").strip().upper()
        if not symbol:
            continue
        rows.append(
            {
                "input_symbol": (h.name_or_token or h.symbol or "").strip(),
                "symbol": symbol,
                "quantity": h.quantity,
                "cost_basis": h.cost_basis,
                "line": None,
            }
        )
    return rows

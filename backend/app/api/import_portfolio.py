"""
Portfolio import endpoint (V26).

POST /api/portfolio/parse — a DRY-RUN parser. It turns a CSV blob or a free-text
paste into a reviewable ImportPreview; it never writes. The only writer stays
POST /api/portfolio, called after the user reviews/edits the preview. That
one-save-funnel invariant is what makes import safe: it can't bypass the
editor's save-time validation, and it can't corrupt a portfolio.

CSV is parsed deterministically (no LLM). Free text makes exactly ONE structured
LLM call, run in a worker thread under a wall-clock timeout, and the text path is
auth-gated + per-user rate-limited because it spends OpenAI tokens on arbitrary
input. Input size caps live in the Pydantic model (over-cap -> 422).
"""

import asyncio
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_user
from app.schemas.import_portfolio import ImportPreview, ImportRequest
from app.services.nl_import import LLM_TIMEOUT_SECONDS, NLParseError, parse_text
from app.services.portfolio_import import (
    normalize_rows,
    parse_csv,
    validate_holdings,
)

router = APIRouter()

# In-process per-user rate limit applied to BOTH modes. Text spends OpenAI
# tokens; CSV issues up to ~100 upstream price lookups per call — both can
# stampede, so one limiter guards the whole endpoint. Mirrors the existing
# _trending_lock / alert-cooldown patterns (no Redis). Per-worker, not
# cluster-global; documented as needing a shared store for multi-worker prod.
_RATE_MAX = 10
_RATE_WINDOW = 300.0  # 5 minutes
_parse_calls: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()


def _rate_retry_after(user_id: str) -> int | None:
    """Record a parse call; return seconds-to-wait if over the limit, else None
    (and count this call)."""
    now = time.monotonic()
    with _rate_lock:
        # Opportunistically prune users whose window has fully expired so the
        # dict can't grow unbounded over the process lifetime.
        if len(_parse_calls) > 256:
            stale = [
                u
                for u, d in _parse_calls.items()
                if not d or now - d[-1] > _RATE_WINDOW
            ]
            for u in stale:
                del _parse_calls[u]
        dq = _parse_calls[user_id]
        while dq and now - dq[0] > _RATE_WINDOW:
            dq.popleft()
        if len(dq) >= _RATE_MAX:
            return int(_RATE_WINDOW - (now - dq[0])) + 1
        dq.append(now)
        return None


@router.post(
    "/api/portfolio/parse",
    response_model=ImportPreview,
    summary="Parse a CSV or free-text holdings list into a reviewable preview (V26)",
)
async def parse_import(
    payload: ImportRequest,
    current_user: str = Depends(require_user),
) -> ImportPreview:
    """Dry-run parse. No DB dependency — this endpoint never writes."""
    if payload.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only import into your own portfolio.",
        )

    retry = _rate_retry_after(current_user)
    if retry is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many imports — please wait a moment and try again.",
            headers={"Retry-After": str(retry)},
        )

    warnings: list = []
    errors: list = []

    if payload.mode == "csv":
        rows, errors, warnings = parse_csv(payload.content)
    else:
        try:
            rows = await asyncio.wait_for(
                asyncio.to_thread(parse_text, payload.content),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        except (NLParseError, asyncio.TimeoutError):
            # A clean preview with a message beats a 500 — the user just retries
            # or switches to CSV.
            return ImportPreview(
                mode="text",
                rows=[],
                parse_error=(
                    "Couldn't read that as a holdings list — try one holding per "
                    "line, or use the CSV format."
                ),
            )

    rows, cap_errors, truncated = normalize_rows(rows)
    # validate_holdings issues blocking market-data lookups (lookup_symbol); run
    # it off the event loop so a cold batch can't freeze the worker.
    preview_rows = await asyncio.to_thread(validate_holdings, rows)
    return ImportPreview(
        mode=payload.mode,
        rows=preview_rows,
        errors=errors + cap_errors,
        warnings=warnings,
        truncated=truncated,
    )

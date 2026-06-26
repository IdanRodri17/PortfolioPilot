"""
CRUD endpoints for portfolio management.

POST /api/portfolio              upsert (create or full-replace)
GET  /api/portfolio/{user_id}    fetch the current portfolio

These are the first handlers to consume the V2 get_db yield-generator
dependency. Each request gets a fresh Session, returned to the pool
on handler completion (or exception) via get_db's finally clause.

Both handlers are sync `def`, not `async def`: SQLAlchemy's Session
is blocking, and FastAPI runs sync handlers in a threadpool so the
event loop stays free. Marking them async would block the loop on
every DB call. V1's /api/generate-report stays async because it
awaits graph.ainvoke(); these handlers have no awaitables.

Versioning:
    V2: this file.
    V5: may add GET /api/portfolio/{user_id}/history if snapshot
        history is exposed; currently only the latest row is kept.
"""

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_owner_or_demo, require_user
from app.db.base import get_db
from app.db.models import User, Portfolio
from app.schemas.portfolio import (
    PortfolioRequest,
    PortfolioResponse,
    WatchlistRequest,
)
from app.tools.stock_data import (
    StockDataError,
    fetch_trending_quotes,
    lookup_symbol,
    usd_ils_rate,
)

router = APIRouter()

# ─── Trending / popular stocks (V22) ─────────────────────────────────────────
# A curated set of widely-held / high-interest US names. Honest "popular stocks"
# rather than a live social-trending feed (no extra API key needed); the endpoint
# ranks them by absolute 24h move so the card surfaces the day's biggest movers.
_TRENDING: list[tuple[str, str]] = [
    ("NVDA", "NVIDIA"),
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("AMZN", "Amazon"),
    ("GOOGL", "Alphabet"),
    ("META", "Meta Platforms"),
    ("TSLA", "Tesla"),
    ("AMD", "AMD"),
    ("NFLX", "Netflix"),
    ("AVGO", "Broadcom"),
    ("PLTR", "Palantir"),
    ("COIN", "Coinbase"),
]
_TRENDING_TTL_SECONDS = 900.0  # 15 min — quotes are cached so we fetch rarely
_trending_cache: dict = {"ts": 0.0, "rows": []}
_trending_lock = threading.Lock()


def _to_response(user: User, portfolio: Portfolio) -> PortfolioResponse:
    """Shape the two ORM rows into one denormalized response object."""
    return PortfolioResponse(
        user_id=user.id,
        assets=portfolio.assets,
        cost_basis=portfolio.cost_basis or {},
        risk_profile=user.risk_profile,
        updated_at=portfolio.updated_at,
    )


@router.post(
    "/api/portfolio",
    response_model=PortfolioResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or replace a user's portfolio",
)
def upsert_portfolio(
    payload: PortfolioRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_user),
) -> PortfolioResponse:
    """Upsert User + Portfolio for the given user_id.

    Semantics:
        - User missing → create both rows.
        - User exists  → update risk_profile, replace assets dict.

    Atomicity:
        One transaction. db.commit() persists both writes together;
        on exception the session teardown in get_db rolls back via
        connection close.

    Race window:
        This is read-then-write, not ON CONFLICT. Two concurrent
        POSTs for the same user_id could race. Acceptable for the
        bootcamp demo's single-user-at-a-time pattern; harden in
        production with a row-level lock or a true upsert query.
    """
    if payload.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own portfolio.",
        )

    user = db.get(User, payload.user_id)

    if user is None:
        # First-time write for this user — create both rows.
        user = User(id=payload.user_id, risk_profile=payload.risk_profile)
        user.portfolio = Portfolio(
            user_id=user.id, assets=payload.assets, cost_basis=payload.cost_basis
        )
        db.add(user)
    else:
        user.risk_profile = payload.risk_profile
        if user.portfolio is None:
            # Defensive: shouldn't occur via this API but possible if
            # rows were ever created manually.
            user.portfolio = Portfolio(
                user_id=user.id, assets=payload.assets, cost_basis=payload.cost_basis
            )
        else:
            # JSONB columns don't track in-place mutation — assign a
            # whole new dict so SQLAlchemy flags the column as dirty.
            user.portfolio.assets = payload.assets
            user.portfolio.cost_basis = payload.cost_basis

    db.commit()
    db.refresh(user.portfolio)  # pulls back the server-side updated_at
    return _to_response(user, user.portfolio)


@router.get(
    "/api/portfolio/{user_id}",
    response_model=PortfolioResponse,
    summary="Fetch the current portfolio for a user",
)
def get_portfolio(
    user_id: str,
    db: Session = Depends(get_db),
    _owner: str = Depends(require_owner_or_demo),
) -> PortfolioResponse:
    """Return the latest portfolio + risk_profile for user_id, else 404.

    Demo-readable (V15a): the curated demo user is public; others need a token.
    """
    user = db.get(User, user_id)
    if user is None or user.portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No portfolio found for user_id '{user_id}'.",
        )
    return _to_response(user, user.portfolio)


@router.get(
    "/api/watchlist/{user_id}",
    summary="Tracked tickers (not owned) with live price + 24h change (V25)",
)
def get_watchlist(
    user_id: str,
    db: Session = Depends(get_db),
    _owner: str = Depends(require_owner_or_demo),
) -> dict:
    """Return the user's watchlist symbols + a live quote for each. Demo-readable
    (same gate as the portfolio). A symbol whose quote can't be fetched still
    appears, with null price/change, so the user never loses track of it."""
    user = db.get(User, user_id)
    symbols = list(user.watchlist or []) if user else []
    quotes = fetch_trending_quotes(symbols) if symbols else {}
    items = [
        {
            "symbol": s,
            "price": quotes.get(s, {}).get("price"),
            "change_24h_percent": quotes.get(s, {}).get("change_24h_percent"),
        }
        for s in symbols
    ]
    return {"symbols": symbols, "items": items}


@router.put(
    "/api/watchlist/{user_id}",
    summary="Replace the user's watchlist (V25)",
)
def put_watchlist(
    user_id: str,
    payload: WatchlistRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_user),
) -> dict:
    """Full-replace the watchlist (normalized + deduped at the boundary)."""
    if user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own watchlist.",
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found for user_id '{user_id}'.",
        )
    user.watchlist = payload.symbols  # reassign so SQLAlchemy flags the JSONB dirty
    db.commit()
    return {"symbols": payload.symbols}


@router.get(
    "/api/ticker/validate",
    summary="Validate a ticker symbol and return its name + price",
)
def validate_ticker(symbol: str) -> dict:
    """Look up one ticker so the editor can validate symbols inline.

    Thin and cached (the cache lives in stock_data.lookup_symbol). No DB, no
    auth — it exposes only public market data, so it stays a plain sync def.

    Response shapes:
        - known ticker:   {"found": true,  "symbol", "name", "price"}
        - unknown ticker: {"found": false, "symbol"}                 (HTTP 200)
        - fetch failure:  HTTP 502                                   (so the
          client can tell a typo apart from a provider outage and degrade
          gracefully — allowing save with a soft warning rather than blocking).
    """
    symbol_norm = symbol.strip().upper()
    if not symbol_norm:
        return {"found": False, "symbol": symbol_norm}

    try:
        result = lookup_symbol(symbol_norm)
    except StockDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    if result is None:
        return {"found": False, "symbol": symbol_norm}
    return {
        "found": True,
        "symbol": symbol_norm,
        "name": result["name"],
        "price": result["price"],
        "currency": result.get("currency", "USD"),
    }


@router.get(
    "/api/fx/usd-ils",
    summary="USD->ILS rate (ILS per 1 USD), for the base-currency display toggle",
)
def usd_ils() -> dict:
    """Public: the rate the frontend uses to display USD-canonical report values
    in shekels when the user picks an ILS base currency (V17). No user data."""
    return {"ils_per_usd": usd_ils_rate()}


@router.get(
    "/api/trending",
    summary="Popular stocks with live price + 24h change (public, cached ~15m)",
)
def trending(limit: int = 10) -> dict:
    """Curated popular US tickers with live price + 24h move, ranked by the size
    of the day's move (V22). Public market data — no auth. Cached process-wide so
    repeated dashboard loads don't refetch; the lock serializes the batch fetch on
    a cache miss so concurrent requests don't stampede yfinance."""
    limit = max(1, min(limit, len(_TRENDING)))
    with _trending_lock:
        now = time.monotonic()
        rows = _trending_cache["rows"]
        if not rows or (now - _trending_cache["ts"]) > _TRENDING_TTL_SECONDS:
            names = dict(_TRENDING)
            quotes = fetch_trending_quotes([s for s, _ in _TRENDING])
            rows = [
                {
                    "symbol": s,
                    "name": names[s],
                    "price": q["price"],
                    "change_24h_percent": q["change_24h_percent"],
                }
                for s, q in ((s, quotes.get(s)) for s in names)
                if q
            ]
            rows.sort(key=lambda r: abs(r["change_24h_percent"]), reverse=True)
            # Only cache a non-empty result, so a transient yfinance failure
            # doesn't pin an empty list for the whole TTL.
            if rows:
                _trending_cache["rows"] = rows
                _trending_cache["ts"] = now
        rows = _trending_cache["rows"] or rows
    return {"stocks": rows[:limit]}

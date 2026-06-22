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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_owner_or_demo, require_user
from app.db.base import get_db
from app.db.models import User, Portfolio
from app.schemas.portfolio import PortfolioRequest, PortfolioResponse
from app.tools.stock_data import StockDataError, lookup_symbol

router = APIRouter()


def _to_response(user: User, portfolio: Portfolio) -> PortfolioResponse:
    """Shape the two ORM rows into one denormalized response object."""
    return PortfolioResponse(
        user_id=user.id,
        assets=portfolio.assets,
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
        user.portfolio = Portfolio(user_id=user.id, assets=payload.assets)
        db.add(user)
    else:
        user.risk_profile = payload.risk_profile
        if user.portfolio is None:
            # Defensive: shouldn't occur via this API but possible if
            # rows were ever created manually.
            user.portfolio = Portfolio(user_id=user.id, assets=payload.assets)
        else:
            # JSONB columns don't track in-place mutation — assign a
            # whole new dict so SQLAlchemy flags the column as dirty.
            user.portfolio.assets = payload.assets

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
    }

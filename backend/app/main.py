"""
FastAPI application entry point.

Run with: uvicorn app.main:app --reload  (from backend/)

The create_app() factory pattern enables per-test app instances. V5 adds a
lifespan context manager: database/store provisioning that needs paired
startup AND shutdown hooks now lives there rather than as an imperative
call at construction time.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Importing config first ensures load_dotenv() runs and Settings is
# validated before anything else (e.g., the graph) tries to touch env vars.
from app.core.config import get_settings
from app.db.base import Base, engine

# Side-effect import: registers User, Portfolio (and V5's Report once it
# lands) on Base.metadata so create_all() actually creates them. Without
# this line, Base.metadata is empty at startup and the tables never get made.
import app.db.models  # noqa: F401

from app.graph.persistence.store import open_store, close_store
from app.graph.persistence.checkpointer import open_checkpointer, close_checkpointer
from app.api.generate import router as generate_router
from app.api.portfolio import router as portfolio_router
from app.api.reports import router as reports_router
from app.api.memories import router as memories_router
from app.graph.builder import set_checkpointer
from app.api.delivery import router as delivery_router
from app.api.telegram import router as telegram_router
from app.api.deliveries import router as deliveries_router

# Browser origins permitted to call the API. The Next.js dev server runs on
# :3000 — a different origin from the backend's :8000 — so its EventSource
# and fetch calls are cross-origin and the browser blocks them without these
# headers. curl sends no Origin, which is why SSE smoke tests pass without it.
_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks for process-wide persistence.

    Startup provisions both persistence layers in one place:
        - Base.metadata.create_all: the Idan-owned tables (users, portfolios,
          and V5's reports). Idempotent CREATE TABLE IF NOT EXISTS.
        - open_store: opens the psycopg pool and runs PostgresStore.setup()
          (CREATE EXTENSION vector + the store/store_vectors tables).
          Idempotent too — warm restarts and --reload are a no-op.

    Shutdown closes the store's connection pool so connections are released
    cleanly. The SQLAlchemy engine pool is process-lifetime and self-managing,
    so it needs no explicit teardown here.

    Why this moved out of create_app() (V2-V4 called create_all imperatively
    at construction): the store pool needs a paired open/close, and a
    module-level call can only do the open half. lifespan owns both ends, so
    all provisioning lives together. V6's PostgresSaver checkpointer setup
    will be added to the startup block below.
    """
    Base.metadata.create_all(bind=engine)
    open_store()
    checkpointer = await open_checkpointer()
    set_checkpointer(checkpointer)
    yield
    await close_checkpointer()
    close_store()


def create_app() -> FastAPI:
    """Construct the FastAPI application.

    Settings are validated at construction so missing env vars fail boot
    rather than the first request. Table/store provisioning happens in the
    lifespan context manager above, not here — so constructing the app no
    longer touches the database (cleaner for tests).
    """
    # Fail-fast settings validation. Raises ValidationError on missing vars.
    get_settings()

    app = FastAPI(
        title="PortfolioPilot",
        version="0.6.0",
        description="AI wealth manager —  V6 (guardrail loop + HITL memory)",
        lifespan=lifespan,
    )

    # Starlette middleware wraps the whole app regardless of add order, so
    # every route (incl. the SSE stream) gets the CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", summary="Liveness check")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(generate_router)
    app.include_router(portfolio_router)
    app.include_router(reports_router)
    app.include_router(memories_router)
    app.include_router(delivery_router)
    app.include_router(telegram_router)
    app.include_router(deliveries_router)

    return app


app = create_app()

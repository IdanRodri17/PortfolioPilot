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
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Importing config first ensures load_dotenv() runs and Settings is
# validated before anything else (e.g., the graph) tries to touch env vars.
from app.core.config import get_settings
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.delivery.dispatcher import dispatch_due
from app.db.base import Base, engine

# Side-effect import: registers User, Portfolio (and V5's Report once it
# lands) on Base.metadata so create_all() actually creates them. Without
# this line, Base.metadata is empty at startup and the tables never get made.
import app.db.models
import logging  # noqa: F401

logger = logging.getLogger(__name__)

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
from app.api.auth import router as auth_router

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
    Base.metadata.create_all(bind=engine)
    open_store()
    checkpointer = await open_checkpointer()
    set_checkpointer(checkpointer)

    # In-process delivery scheduler. The tick is intentionally dumb: every N
    # minutes it calls dispatch_due(), which runs the real per-user due check
    # and the last_sent_at dedupe — so an over-frequent tick can never
    # double-send, and swapping this for an external cron that POSTs
    # /api/run-due-deliveries needs zero logic changes.
    #
    # Started here (not at import) because AsyncIOScheduler binds to the running
    # event loop — the same reason the async checkpointer is opened in the
    # lifespan rather than at module load.
    scheduler = AsyncIOScheduler()
    interval = get_settings().due_check_interval_minutes
    scheduler.add_job(
        dispatch_due,
        "interval",
        minutes=interval,
        id="due_deliveries",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(
            timezone.utc
        ),  # fire once on boot, then every interval
    )
    scheduler.start()
    logger.warning(
        "Delivery scheduler started: dispatch_due now, then every %d min", interval
    )

    yield

    scheduler.shutdown(wait=False)
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
    app.include_router(auth_router)

    return app


app = create_app()

"""
FastAPI application entry point.

Run with: uvicorn app.main:app --reload  (from backend/)

The create_app() factory pattern enables per-test app instances and
will make V6's lifespan-managed checkpointer setup a clean extension
rather than a refactor.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Importing config first ensures load_dotenv() runs and Settings is
# validated before anything else (e.g., the graph) tries to touch env vars.
from app.core.config import get_settings
from app.db.base import Base, engine

# Side-effect import: registers User and Portfolio on Base.metadata so
# create_all() actually creates them. Without this line, Base.metadata
# is empty at startup and the tables silently never get made.
import app.db.models  # noqa: F401

from app.api.generate import router as generate_router
from app.api.portfolio import router as portfolio_router


# Browser origins permitted to call the API. The Next.js dev server (V4b)
# runs on :3000 — a different origin from the backend's :8000 — so its
# EventSource and fetch calls are cross-origin and the browser blocks them
# without these response headers. curl sends no Origin, which is why the
# V4a SSE smoke test passed before this middleware existed: the browser is
# the first cross-origin caller. Replace with the real deployed origin
# (or read from settings) post-MVP.
_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def create_app() -> FastAPI:
    """Construct the FastAPI application.

    Settings are validated at app construction so missing env vars
    fail boot rather than fail the first request. Tables are then
    created idempotently — CREATE TABLE IF NOT EXISTS per table —
    so a fresh Postgres volume bootstraps automatically.

    V6 will likely move table creation (and PostgresSaver setup)
    into a lifespan context manager. For V2-V5 the imperative call
    at construction time is sufficient.
    """
    # Fail-fast settings validation. Raises ValidationError on missing required vars.
    get_settings()

    # Idempotent: skips tables that already exist. No-op on warm restarts.
    Base.metadata.create_all(bind=engine)

    app = FastAPI(
        title="PortfolioPilot",
        version="0.4.0",
        description="AI wealth manager — V4 (SSE streaming over the V3 multi-agent graph)",
    )

    # Starlette middleware wraps the whole app regardless of when it's
    # added relative to the routers, so every route (incl. the SSE
    # stream) gets the CORS headers.
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

    return app


app = create_app()

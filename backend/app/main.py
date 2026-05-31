"""
FastAPI application entry point.

Run with: uvicorn app.main:app --reload  (from backend/)

The create_app() factory pattern enables per-test app instances and
will make V6's lifespan-managed checkpointer setup a clean extension
rather than a refactor.
"""

from fastapi import FastAPI

# Importing config first ensures load_dotenv() runs and Settings is
# validated before anything else (e.g., the graph) tries to touch env vars.
from app.core.config import get_settings
from app.db.base import Base, engine

# Side-effect import: registers User and Portfolio on Base.metadata so
# create_all() actually creates them. Without this line, Base.metadata
# is empty at startup and the tables silently never get made.
import app.db.models  # noqa: F401

from app.api.generate import router as generate_router


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
        version="0.2.0",
        description="AI wealth manager — V2 (DB-backed portfolio CRUD)",
    )

    @app.get("/api/health", summary="Liveness check")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(generate_router)

    return app


app = create_app()

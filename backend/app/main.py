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
from app.api.generate import router as generate_router


def create_app() -> FastAPI:
    """Construct the FastAPI application.

    Settings are validated at app construction so missing env vars
    fail boot rather than fail the first request.
    """
    # Fail-fast settings validation. Raises ValidationError on missing required vars.
    get_settings()

    app = FastAPI(
        title="PortfolioPilot",
        version="0.1.0",
        description="AI wealth manager — V1 (linear graph, hardcoded portfolio)",
    )

    @app.get("/api/health", summary="Liveness check")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(generate_router)

    return app


app = create_app()

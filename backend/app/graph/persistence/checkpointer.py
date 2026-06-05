"""
Async LangGraph checkpointer — the PostgresSaver for HITL pause/resume (V6).

Target path: backend/app/graph/persistence/checkpointer.py

The checkpointer persists a snapshot of graph state at every super-step,
keyed by thread_id (we reuse report_id). It is what makes interrupt()
resumable: when human_review calls interrupt(), the runtime saves the snapshot
here, the run exits, and a later Command(resume=...) reads it back and restarts
at the interrupted node.

Why ASYNC (AsyncPostgresSaver, not the sync PostgresSaver the SRS sketched):
    The graph runs via graph.astream_events(...) — the async Pregel runtime,
    which calls the checkpointer's async methods. The sync PostgresSaver leaves
    those unimplemented (NotImplementedError under an async run). The store
    stays sync because it's called from inside sync nodes (threadpool) — a
    different code path from the runtime-managed checkpointer.

Why construction is DEFERRED to open_checkpointer() (not module import):
    AsyncPostgresSaver.__init__ calls asyncio.get_running_loop() to bind to its
    loop. At import there is no running loop -> RuntimeError. So we build BOTH
    the async pool and the saver inside open_checkpointer(), which the lifespan
    awaits — i.e. inside uvicorn's running loop, the same loop that serves every
    request. builder.set_checkpointer() then recompiles the graph singleton with
    it. (Its own async pool, separate from the store's sync pool, against the
    same Postgres DB.)

Versioning:
    V6: AsyncPostgresSaver, built in the lifespan and compiled into the graph
        alongside the store.
"""

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import get_settings

# Constructed in open_checkpointer() (inside the running loop), not at import.
_pool: AsyncConnectionPool | None = None
checkpointer: AsyncPostgresSaver | None = None


def _checkpointer_conninfo() -> str:
    """Same +psycopg -> libpq translation the store does (see store.py)."""
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


async def open_checkpointer() -> AsyncPostgresSaver:
    """Build + open the async pool and the saver IN the running loop, then
    provision its tables. Returns the saver so the lifespan can hand it to
    builder.set_checkpointer().

    setup() is idempotent (CREATE TABLE IF NOT EXISTS for checkpoints,
    checkpoint_blobs, checkpoint_writes, checkpoint_migrations), so warm
    restarts and --reload are no-ops.
    """
    global _pool, checkpointer
    _pool = AsyncConnectionPool(
        conninfo=_checkpointer_conninfo(),
        open=False,
        kwargs={"autocommit": True},
    )
    await _pool.open()
    checkpointer = AsyncPostgresSaver(conn=_pool)
    await checkpointer.setup()
    return checkpointer


async def close_checkpointer() -> None:
    """Close the async pool on app shutdown, releasing all connections."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

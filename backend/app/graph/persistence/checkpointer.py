"""
Async LangGraph checkpointer — the PostgresSaver for HITL pause/resume (V6).

Target path: backend/app/graph/persistence/checkpointer.py

The checkpointer persists a snapshot of graph state at every super-step,
keyed by thread_id (we reuse report_id). It is what makes interrupt()
resumable: when human_review calls interrupt(), the runtime saves the
snapshot here, the run exits, and a later Command(resume=...) reads this
snapshot back and restarts at the interrupted node.

Why ASYNC (AsyncPostgresSaver, not the sync PostgresSaver the SRS sketched):
    The graph is driven by graph.astream_events(...) — the async Pregel
    runtime. The runtime calls the checkpointer's *async* methods
    (aget_tuple/aput/...). The sync PostgresSaver implements only the sync
    methods; under an async run those async methods raise NotImplementedError.
    AsyncPostgresSaver implements the async side, so it is the correct pair
    for our SSE streaming. (The store stays sync because it is called from
    inside sync nodes, which LangGraph runs in a threadpool — a different code
    path from the runtime-managed checkpointer.)

Why its OWN async pool (separate from the store's sync pool):
    AsyncPostgresSaver needs an AsyncConnectionPool; the store's pool is the
    sync ConnectionPool. They cannot be the same object. So this module owns
    a second psycopg pool — async — against the same Postgres DB. Same
    open=False / autocommit=True discipline as the store pool: imports stay
    DB-free, DDL/writes need autocommit. open/close are awaited in lifespan.

Versioning:
    V6: AsyncPostgresSaver added here, compiled into the graph alongside the
        store via builder.compile(checkpointer=..., store=...).
"""

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import get_settings


def _checkpointer_conninfo() -> str:
    """Same +psycopg -> libpq translation the store does (see store.py).

    psycopg's pool passes conninfo straight to libpq, which rejects
    SQLAlchemy's postgresql+psycopg:// dialect marker. The replace is a
    no-op if the URL is already a plain postgresql:// one.
    """
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


# Async pool dedicated to the checkpointer. open=False keeps importing this
# module (which builder.py does to compile the graph) DB-free; the pool is
# opened in main.py's lifespan. autocommit=True is required for setup()'s DDL
# and the saver's writes.
_pool = AsyncConnectionPool(
    conninfo=_checkpointer_conninfo(),
    open=False,
    kwargs={"autocommit": True},
)

# The checkpointer singleton, compiled into the graph in builder.py.
checkpointer = AsyncPostgresSaver(conn=_pool)


async def open_checkpointer() -> None:
    """Open the async pool and provision checkpointer tables (lifespan startup).

    setup() is idempotent (CREATE TABLE IF NOT EXISTS for checkpoints,
    checkpoint_blobs, checkpoint_writes, checkpoint_migrations), so warm
    restarts and --reload are no-ops.
    """
    await _pool.open()
    await checkpointer.setup()


async def close_checkpointer() -> None:
    """Close the async pool on app shutdown, releasing all connections."""
    await _pool.close()

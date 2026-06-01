"""
Semantic long-term memory — the PostgresStore singleton (V5).

This is the project's first piece of LangGraph-managed persistence, and
it is deliberately separate from the SQLAlchemy layer in db/.

How it differs from db/ (User, Portfolio, Report):
    - We do NOT declare its schema. store.setup() creates the `store` and
      `store_vectors` tables and runs CREATE EXTENSION vector. There is no
      ORM model for memories (SRS §6.2) — by design.
    - Records are addressed by a namespace tuple + key, e.g.
      store.put(("memories", user_id), key, {"insight": "..."}).
    - Retrieval is by SEMANTIC SIMILARITY: store.search(namespace, query=...)
      embeds the query, cosine-searches the embedded field via pgvector, and
      returns the closest matches with .score. This is what lets memory_loader
      (step 3) surface only the relevant past insights for the current
      portfolio rather than every memory ever stored.

Lifecycle:
    The pool is created with open=False so importing this module (which
    builder.py does to compile the graph with the store) never touches the
    database. main.py's lifespan (step 2) calls open_store() on startup and
    close_store() on shutdown. V6's PostgresSaver checkpointer will join this
    same package and reuse the same lifecycle shape.

Versioning:
    V5: PostgresStore for semantic memory (this file).
    V6: PostgresSaver checkpointer added alongside (persistence/checkpointer.py),
        opened/closed in the same lifespan.
"""

from psycopg_pool import ConnectionPool
from langgraph.store.postgres import PostgresStore

from app.core.config import get_settings


def _store_conninfo() -> str:
    """Translate the SQLAlchemy DATABASE_URL into a libpq conninfo string.

    DATABASE_URL is written for SQLAlchemy: postgresql+psycopg://...
    The +psycopg suffix is SQLAlchemy's driver/dialect marker. psycopg's
    own ConnectionPool passes conninfo straight to libpq, which only
    understands postgresql:// (or postgres://) — the +psycopg breaks scheme
    parsing. Same database, same credentials; we just drop the marker.

    The replace is a no-op if the URL is already a plain postgresql:// one,
    so this is safe regardless of how DATABASE_URL is written.
    """
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


# Connection pool dedicated to the LangGraph persistence layer (store now,
# checkpointer in V6). Separate from db/base.py's SQLAlchemy engine pool by
# necessity: SQLAlchemy hands out SQLAlchemy Connection objects, but
# PostgresStore needs raw psycopg connections. Two pools, one Postgres DB.
#
#   open=False        Do not connect at import time. builder.py imports this
#                     module to compile the graph with the store, and that
#                     import must not require a live database. The pool is
#                     opened explicitly in main.py's lifespan.
#   autocommit=True   Required by LangGraph's Postgres persistence. setup()
#                     runs DDL (CREATE EXTENSION, CREATE TABLE) and the
#                     store's writes assume autocommit; without it setup()
#                     and put() misbehave.
_pool = ConnectionPool(
    conninfo=_store_conninfo(),
    open=False,
    kwargs={"autocommit": True},
)

# The store singleton. index={...} enables semantic search:
#   embed   Which embedding model converts text -> vector. The string form
#           "openai:text-embedding-3-small" is resolved by langchain; it
#           reads OPENAI_API_KEY from the environment (loaded in config.py).
#   dims    1536 — the dimensionality of text-embedding-3-small. Must match
#           the model exactly or pgvector rejects the embeddings on insert.
#   fields  Which fields of each stored value get embedded. We embed only
#           "insight" (the natural-language sentence we search on). Other
#           fields in the value (e.g. "context") are stored but not embedded,
#           so they don't dilute the similarity signal.
store = PostgresStore(
    conn=_pool,
    index={
        "embed": "openai:text-embedding-3-small",
        "dims": 1536,
        "fields": ["insight"],
    },
)


def open_store() -> None:
    """Open the pool and provision the store (startup, called from lifespan).

    Order matters: the pool must be open before setup() requests a
    connection. setup() is idempotent — CREATE EXTENSION IF NOT EXISTS /
    CREATE TABLE IF NOT EXISTS — so warm restarts are a no-op.
    """
    _pool.open()
    store.setup()


def close_store() -> None:
    """Close the pool on app shutdown, releasing all connections."""
    _pool.close()

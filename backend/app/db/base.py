"""
Database engine, session factory, declarative base, and the
request-scoped session dependency.

V1 introduced one DI shape: @lru_cache-wrapped providers for
process-wide singletons (Settings, the compiled graph). V2 adds a
second shape: a yield-generator provider for *request-scoped*
resources. Both are accessed via Depends() in handlers, but their
lifecycles are opposite — singletons live forever, sessions live for
exactly one request.

Versioning:
    V2: engine, SessionLocal, Base, get_db.
    V5: PostgresStore singleton lands in its own module
        (graph/persistence/store.py) and uses the same DATABASE_URL.
    V6: PostgresSaver checkpointer joins the persistence layer.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import get_settings

# ─── Engine ───────────────────────────────────────────────────────────
# The engine owns a connection pool. One engine per process, created
# once at import time. Connections are checked out per-session and
# returned to the pool on session.close(). `pool_pre_ping=True` makes
# the pool verify a connection is alive before handing it out — catches
# the case where Postgres has dropped an idle connection (very common
# behind cloud load balancers or after Docker pauses overnight).
engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    future=True,  # opt into SQLAlchemy 2.x execution style
)

# ─── Session factory ─────────────────────────────────────────────────
# SessionLocal() returns a brand-new Session bound to the engine.
# autocommit=False: no implicit commits — handlers explicitly call
#     db.commit() to make changes durable.
# autoflush=False: ORM doesn't push pending changes to the DB on every
#     query — gives handlers control over when SQL fires. Both are the
#     conventional FastAPI defaults.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # objects remain usable after commit; avoids
    # accidental lazy-load explosions in handlers
)

# ─── Declarative base ────────────────────────────────────────────────
# Every model class inherits from this. SQLAlchemy collects their
# metadata so Base.metadata.create_all() (V2 step 3) can issue CREATE
# TABLE for the whole set in one call.
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped DB session.

    Usage in a handler:
        def handler(db: Session = Depends(get_db)):
            db.query(...).all()

    The yield-and-finally pattern guarantees db.close() runs even if
    the handler raises, returning the connection to the pool. Without
    the finally, an unhandled exception in a handler would leak a
    connection per failed request — under load, the pool drains and
    the app hangs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

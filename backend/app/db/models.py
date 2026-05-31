"""
ORM models for PortfolioPilot.

V2: User and Portfolio (this file).
V5: Report (historical persisted reports).
V8 stretch: User.telegram_chat_id column added.

The langgraph.store.postgres tables for semantic memory (V5) are not
declared here — they are auto-managed by store.setup() and live
outside this Base.metadata namespace by design.
"""

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    """One row per portfolio owner.

    Primary key is a string (e.g. "idan_demo") rather than autoincrement
    int — keeps user_ids stable, human-readable, and URL-safe. Real
    auth (V7) will replace this with NextAuth-issued IDs but the column
    type doesn't need to change.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    risk_profile = Column(
        String, nullable=False
    )  # "conservative" | "balanced" | "aggressive"

    # Timestamps come from Postgres (func.now()), not Python.
    # Two benefits over datetime.utcnow as a Python-side default:
    #   1. Avoids the Python 3.12 datetime.utcnow() DeprecationWarning.
    #   2. Timestamps are consistent regardless of which app server
    #      inserts the row — the DB is the single clock.
    # timezone=True stores as TIMESTAMPTZ, the correct Postgres default.
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # uselist=False makes this a scalar (1-to-1), not a list (1-to-many).
    # Each user has exactly one portfolio row in V2.
    portfolio = relationship(
        "Portfolio",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Portfolio(Base):
    """One row per user holding their full asset map.

    The `assets` column is JSONB rather than a normalized holdings
    table for three reasons:
      1. Read pattern: always fetched as a unit ("give me this user's
         whole portfolio"). We never query "find all users holding AAPL".
      2. Shape match: the dict on disk has the exact same structure as
         what the graph receives — no transformation layer needed.
      3. Symbol set is open and heterogeneous (stocks + crypto +
         possibly TASE later). A normalized table would either lose
         that flexibility or need a discriminator column.

    If a "find users holding X" query is ever needed, Postgres supports
    JSONB containment ops (`assets ? 'AAPL'`) and GIN indexes. No
    structural change required.
    """

    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # unique=True enforces the 1-to-1 with users at the DB level —
    # ON CONFLICT (user_id) DO UPDATE is then a valid upsert. Without
    # unique, the upsert in api/portfolio.py would have to do a
    # SELECT-then-INSERT-or-UPDATE dance with a race window.
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    assets = Column(JSONB, nullable=False)
    # Example: {"AAPL": 10.0, "TEVA.TA": 25.0, "BTC": 0.5}

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="portfolio")

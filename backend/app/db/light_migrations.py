"""Idempotent, additive column migrations for already-existing databases (V18).

The project creates tables with `Base.metadata.create_all` (db/base.py), which
issues CREATE TABLE for NEW tables but never alters EXISTING ones. So when a
feature adds a column to a table that already has rows — e.g. V18's alert fields
on `delivery_preferences` — create_all silently skips it, and the ORM then
references a column the live DB doesn't have.

This module bridges that gap with Postgres `ADD COLUMN IF NOT EXISTS`, run on
every boot right after create_all:
  - on an existing DB, it adds the missing columns (existing rows get the
    DEFAULT) and is a no-op on the next boot;
  - on a fresh DB, create_all already made the column from the model, so the
    IF NOT EXISTS short-circuits.

No Alembic: every statement here is purely additive and backward-compatible
(the project's "schema stays additive/optional" rule), which is exactly what
ADD COLUMN IF NOT EXISTS is safe for. Anything non-additive (a drop, a rename,
a type change) does NOT belong here.
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Each entry is a single idempotent, additive DDL statement.
_STATEMENTS = (
    # ── V18: threshold alerts on delivery_preferences ──
    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS "
    "alerts_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS "
    "alert_price_move_pct DOUBLE PRECISION",
    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS "
    "alert_portfolio_move_pct DOUBLE PRECISION",
    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS "
    "alert_concentration_pct DOUBLE PRECISION",
    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS "
    "alert_cooldown_hours INTEGER NOT NULL DEFAULT 12",
    "ALTER TABLE delivery_preferences ADD COLUMN IF NOT EXISTS "
    "alert_state JSONB NOT NULL DEFAULT '{}'::jsonb",
)


def run_light_migrations(engine: Engine) -> None:
    """Apply each additive statement in its OWN transaction.

    Per-statement transactions matter on Postgres: an error leaves the current
    transaction in an aborted state where every later statement also fails, so
    one bad ALTER must not poison the rest. Each failure is logged and skipped;
    startup is never blocked by a migration hiccup.
    """
    for stmt in _STATEMENTS:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception:  # noqa: BLE001 — a failed migration can't sink boot
            logger.exception("light migration failed: %s", stmt)

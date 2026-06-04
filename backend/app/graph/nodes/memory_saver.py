"""
memory_saver node — persists the user-approved insights (V6).

Target path: backend/app/graph/nodes/memory_saver.py

Runs last (human_review -> memory_saver -> END), only after human_review's
interrupt captured the user's approvals into approved_memories. This is the
node that actually writes to the PostgresStore — the write that lived in V5's
memory_extractor moved here, behind the human approval gate.

Store injection: like memory_loader, it takes a keyword-only store: BaseStore,
supplied by builder.compile(store=...). It never imports the store singleton,
which keeps it unit-testable (pass a store in) and leaves lifecycle to the
framework.

Storage shape: each saved value is {"insight": str} — identical to V5's
stored shape, so memory_loader's search and the /api/memories endpoint keep
working unchanged. (The SRS's optional "context" field is skipped for now to
preserve that shape; it can be added later without breaking the readers.)

Graceful degradation (pattern #22): the report was delivered to the user long
ago (in the first SSE stream, before the interrupt). A store-write failure
here must not error the resume stream — we log and save what we can.

Versioning:
    V6: this file.
"""

import logging
from typing import List
from uuid import uuid4

from langgraph.store.base import BaseStore

from app.graph.state import PortfolioState

logger = logging.getLogger(__name__)


def memory_saver(state: PortfolioState, *, store: BaseStore) -> dict:
    """Persist approved insights to the PostgresStore.

    Reads:
        user_id, approved_memories.

    Returns:
        {"new_memories": [{"insight": str}, ...]} — what was actually saved,
        for transparency in the resume stream and the /memory view.

    Namespace:
        ("memories", user_id) — same per-user partition as memory_loader.
    """
    user_id = state["user_id"]
    namespace = ("memories", user_id)
    approved = state.get("approved_memories", [])

    saved: List[dict] = []
    for mem in approved:
        insight = (mem.get("insight") or "").strip()
        if not insight:
            continue
        value = {"insight": insight}
        try:
            store.put(namespace, str(uuid4()), value)
            saved.append(value)
        except Exception as exc:  # noqa: BLE001 — don't sink the resume stream
            logger.warning(
                "memory_saver: failed to persist insight for %s — %s", user_id, exc
            )

    logger.info(
        "memory_saver: saved %d approved memories for %s", len(saved), user_id
    )
    return {"new_memories": saved}

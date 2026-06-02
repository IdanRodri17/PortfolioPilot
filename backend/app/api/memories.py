"""Memory transparency endpoints (V5) — read/wipe the PostgresStore."""

from fastapi import APIRouter

from app.graph.persistence.store import store

router = APIRouter()


def _ns(user_id: str) -> tuple[str, str]:
    return ("memories", user_id)


@router.get("/api/memories/{user_id}", summary="List a user's stored memories")
def list_memories(user_id: str) -> list[dict]:
    """search() with no query = list mode (no semantic ranking). limit high
    enough to return everything for the demo."""
    items = store.search(_ns(user_id), limit=100)
    return [
        {
            "key": it.key,
            "insight": (it.value or {}).get("insight", ""),
            "created_at": (
                it.created_at.isoformat() if getattr(it, "created_at", None) else None
            ),
        }
        for it in items
    ]


@router.delete("/api/memories/{user_id}", summary="Wipe a user's stored memories")
def delete_memories(user_id: str) -> dict:
    """Delete every memory in the namespace (user control / demo reset)."""
    ns = _ns(user_id)
    keys = [it.key for it in store.search(ns, limit=100)]
    for k in keys:
        store.delete(ns, k)
    return {"user_id": user_id, "deleted": len(keys)}

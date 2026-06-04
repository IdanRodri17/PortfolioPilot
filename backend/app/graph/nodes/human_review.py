"""
human_review node — the HITL interrupt point for memory approval (V6).

Target path: backend/app/graph/nodes/human_review.py

Sits between memory_extractor (proposes) and memory_saver (persists). It
calls interrupt() to pause the whole graph and hand the proposed memories to
the user; only the indices the user approves flow on to memory_saver.

The interrupt() mechanic (the one genuinely new thing here):
    First pass — interrupt(payload) RAISES. The runtime saves the graph
    snapshot to the checkpointer (keyed by thread_id) and the run exits. The
    API translates this into the human_input_required SSE event.
    Resume — the client calls the graph again with Command(resume=value) and
    the SAME thread_id. The runtime restores the snapshot, RE-RUNS this node
    from the top, and this time interrupt() RETURNS `value` instead of raising.

    Consequence worth internalizing: everything ABOVE the interrupt() line
    runs twice (once before the pause, once on resume). So keep pre-interrupt
    work trivial and side-effect-free — here it is just reading state. The
    real write (store.put) lives in memory_saver, after the gate, so it never
    double-fires.

Empty-proposal shortcut: if there is nothing to approve, we skip interrupt()
entirely and return an empty approval — no modal, the graph flows straight to
memory_saver -> END, and the first SSE stream ends at report_complete with no
human_input_required event.

Versioning:
    V6: this file. The split (extractor proposes, human_review gates,
        memory_saver persists) is the whole point of HITL — the user is the
        gatekeeper of long-term memory.
"""

import logging

from langgraph.types import interrupt

from app.graph.state import PortfolioState

logger = logging.getLogger(__name__)


def human_review(state: PortfolioState) -> dict:
    """Pause for user approval of proposed memories.

    Reads:
        proposed_memories — candidate insights from memory_extractor.

    Returns:
        {"approved_memories": [...]} — the subset the user approved, or []
        if there was nothing to review.
    """
    proposed = state.get("proposed_memories", [])
    if not proposed:
        # Nothing to approve — don't open an empty modal. Flow straight on.
        return {"approved_memories": []}

    # Pauses the graph. The value returned here on resume is whatever the
    # client passes via Command(resume={"approved_indices": [...]}).
    decisions = interrupt(
        {"type": "memory_review", "proposed_memories": proposed}
    )

    indices = (decisions or {}).get("approved_indices", [])
    approved = [
        proposed[i]
        for i in indices
        if isinstance(i, int) and 0 <= i < len(proposed)
    ]
    logger.info(
        "human_review: %d of %d proposals approved", len(approved), len(proposed)
    )
    return {"approved_memories": approved}

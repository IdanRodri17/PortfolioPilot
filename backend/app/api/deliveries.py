"""
Delivery trigger endpoints (V7).

POST /api/deliveries/run-now/{user_id}   deliver a report to a user immediately

Manual/demo trigger that mirrors the SRS's digest/run-now. It runs the full
delivery for one user regardless of schedule (no due check) — the report is
produced, archived, and sent to every enabled channel. The scheduled trigger
(POST /api/run-due-deliveries) and the due check arrive in V7c-2.

async def: deliver_for_user awaits the graph, so this handler is async (like
generate/resume, unlike the sync DB-only CRUD handlers).

Versioning:
    V7: this file (V7c).
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.delivery.dispatcher import deliver_for_user, DeliveryError, dispatch_due

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/api/deliveries/run-now/{user_id}",
    summary="Deliver a report to a user immediately (ignores schedule)",
)
async def run_now(user_id: str) -> dict:
    """Produce and deliver one report for user_id across their enabled channels.

    Returns the dispatcher result ({report_id, channels} or {skipped}). A
    DeliveryError (no portfolio / no report produced) surfaces as 500 — the
    request was understood, the delivery just couldn't be completed.
    """
    try:
        return await deliver_for_user(user_id)
    except DeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.post(
    "/api/run-due-deliveries",
    summary="Deliver to every user whose schedule is due now",
)
async def run_due_deliveries() -> dict:
    """The scheduled trigger — hit by the in-process APScheduler tick (V7c-2b)
    or an external cron every ~10 min. Idempotent within a period via
    last_sent_at, so over-frequent calls are harmless."""
    return await dispatch_due()

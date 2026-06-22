"""
CRUD endpoints for scheduled-delivery preferences (V7).

GET /api/delivery-preferences/{user_id}   fetch current prefs + channel availability
PUT /api/delivery-preferences/{user_id}   create or full-replace the prefs

Sync `def` like api/portfolio.py: these are pure DB handlers (no graph await),
so FastAPI runs them in the threadpool and the event loop stays free. The
generate/resume endpoints stay async because they await the graph.

Two layers of validation, by design:
    1. schemas/delivery.py (Pydantic) already enforced the self-contained rules
       on the PUT body — at least one channel, the cadence parameter, a valid
       IANA timezone — before this handler runs.
    2. THIS handler enforces the cross-entity rule the boundary model can't: a
       checked channel must have a usable address on the User row. Email needs
       User.email; Telegram needs a linked User.telegram_chat_id. The settings
       UI gates the checkboxes on the same facts (returned by GET), so this is
       a defensive backstop, not the primary UX.

Versioning:
    V7: this file. The connect-Telegram flow (V7b) is what populates
        User.telegram_chat_id; until a user links Telegram, enabling that
        channel here is rejected with 422.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import User, DeliveryPreference
from app.schemas.delivery import DeliveryPreferenceRequest, DeliveryPreferenceResponse
from app.api.deps import require_owner

logger = logging.getLogger(__name__)

router = APIRouter()


def _email_set(user: User) -> bool:
    return bool(user.email and user.email.strip())


def _telegram_connected(user: User) -> bool:
    return bool(user.telegram_chat_id and user.telegram_chat_id.strip())


@router.get(
    "/api/delivery-preferences/{user_id}",
    summary="Fetch a user's delivery preferences + channel availability",
)
def get_delivery_preferences(
    user_id: str,
    db: Session = Depends(get_db),
    _owner: str = Depends(require_owner),
) -> dict:
    """Return the stored preference (or null if never configured) alongside
    which channels are *usable* for this user.

    Shaped dict, not a response_model (pattern #38): the payload joins the
    DeliveryPreference row with two derived booleans off the User row, so the
    settings UI can both populate the form and gate the channel checkboxes in
    one request. 404 only if the user itself doesn't exist.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found for user_id '{user_id}'.",
        )

    pref = user.delivery_preference
    return {
        "user_id": user_id,
        "email_set": _email_set(user),
        "telegram_connected": _telegram_connected(user),
        "preference": (
            DeliveryPreferenceResponse.model_validate(pref).model_dump(mode="json")
            if pref is not None
            else None
        ),
    }


@router.put(
    "/api/delivery-preferences/{user_id}",
    response_model=DeliveryPreferenceResponse,
    summary="Create or replace a user's delivery preferences",
)
def upsert_delivery_preferences(
    user_id: str,
    payload: DeliveryPreferenceRequest,
    db: Session = Depends(get_db),
    _owner: str = Depends(require_owner),
) -> DeliveryPreference:
    """Upsert the preference row after checking the channel addresses exist.

    Pydantic validated the body's internal consistency before we got here.
    What's left is the cross-entity rule: you can't enable a channel you have
    no address for. We reject that with 422 rather than silently storing a
    preference that could never deliver.

    Upsert is read-then-write in one transaction, same shape (and same benign
    single-user race window) as api/portfolio.py.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found for user_id '{user_id}'.",
        )

    # Cross-entity gate: a checked channel needs a usable address.
    if payload.deliver_email and not _email_set(user):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot enable email delivery: this user has no email address on file.",
        )
    if payload.deliver_telegram and not _telegram_connected(user):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot enable Telegram delivery: connect Telegram for this user first.",
        )

    pref = user.delivery_preference
    if pref is None:
        pref = DeliveryPreference(user_id=user_id)
        db.add(pref)

    # Full-replace every field from the validated payload.
    pref.deliver_telegram = payload.deliver_telegram
    pref.deliver_email = payload.deliver_email
    pref.cadence = payload.cadence
    pref.interval_days = payload.interval_days
    pref.weekday = payload.weekday
    pref.send_time_local = payload.send_time_local
    pref.timezone = payload.timezone
    pref.enabled = payload.enabled

    db.commit()
    db.refresh(pref)  # pull the server-side updated_at
    return pref

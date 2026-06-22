"""
Telegram connect endpoint — bind a chat_id to a user (V7).

POST /api/telegram/connect/{user_id}

The lightweight bind (V7 design): the user opens their bot in Telegram and
sends it any message, then hits this endpoint. We do a one-shot getUpdates read,
take the most recent chat that messaged the bot, and store its id on
User.telegram_chat_id. No webhook, no long-poll loop — receiving Telegram
messages locally would otherwise need a public URL (a tunnel) or a standing
poller, far more than binding a single demo user warrants.

Once bound, a deliver_telegram=true delivery preference passes the address gate
in api/delivery.py, and the dispatcher (V7c) can send to this chat.

Versioning:
    V7: this file (V7b).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_owner
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import User
from app.tools.telegram_sender import get_updates, TelegramSendError

logger = logging.getLogger(__name__)

router = APIRouter()


def _latest_chat(updates: list[dict]) -> dict | None:
    """Pick the chat of the most recent message-bearing update.

    getUpdates returns updates oldest-first, so we scan from the end for the
    first one carrying a message.chat. Single-user demo assumption: whoever
    messaged the bot last is the user connecting now.
    """
    for update in reversed(updates):
        chat = (update.get("message") or {}).get("chat")
        if chat and chat.get("id") is not None:
            return chat
    return None


@router.post(
    "/api/telegram/connect/{user_id}",
    summary="Bind the chat that most recently messaged the bot to a user",
)
def connect_telegram(
    user_id: str,
    db: Session = Depends(get_db),
    _owner: str = Depends(require_owner),
) -> dict:
    """Read pending bot updates and bind the latest chat_id to the user.

    Pre-req: the user must have just sent the bot a message — that's what puts a
    chat in getUpdates and unblocks the bot to message them back.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found for user_id '{user_id}'.",
        )

    try:
        updates = get_updates()
    except TelegramSendError as exc:
        # Upstream/config failure reaching Telegram — not the client's fault.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Telegram: {exc}",
        )

    chat = _latest_chat(updates)
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No recent message found. Open your bot in Telegram, send it any "
                "message, then try connecting again."
            ),
        )

    user.telegram_chat_id = str(chat["id"])
    db.commit()

    # Friendly label for the UI confirmation; purely cosmetic.
    name = chat.get("username") or chat.get("first_name") or "your chat"
    logger.info("connect_telegram: bound chat %s to %s", chat["id"], user_id)
    return {
        "user_id": user_id,
        "telegram_chat_id": user.telegram_chat_id,
        "chat_name": name,
    }

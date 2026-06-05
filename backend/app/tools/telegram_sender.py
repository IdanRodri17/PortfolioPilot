"""
Telegram Bot API wrapper — sends a message to a chat (V7).

Single point of contact with the Bot API (pattern #4): services never build
Telegram requests inline, they call send_telegram_message(). One normalized
exception (TelegramSendError) covers every failure mode — missing token, a
transport error, or a Bot API {"ok": false} body.

Send vs receive — the asymmetry worth internalizing:
    SENDING (this file) is stateless and trivial: one HTTPS POST to
    api.telegram.org/bot<token>/sendMessage with the chat_id and text. No
    inbound connectivity required — your process reaches out.
    RECEIVING (the connect flow, next step) is the hard direction: Telegram
    must get a message TO us, either by us long-polling getUpdates (a pull, no
    public URL needed) or by Telegram pushing to a setWebhook URL (which needs
    a public HTTPS endpoint — a tunnel, locally). The lightweight connect flow
    uses a one-shot getUpdates read precisely to avoid standing up a webhook or
    a long-poll loop just to bind a single user.

The token lives in the URL path (…/bot<token>/…), not a header — that's the Bot
API's convention. parse_mode="HTML" matches render_telegram_brief's output
(<b>, <i>, <a>); disable_web_page_preview stops the deep link from expanding
into a bulky preview card under the brief.

Sync def (like stock_data / news_search): the V7c dispatcher will call this via
asyncio.to_thread so a blocking POST never sits on the event loop.

Versioning:
    V7: this file (V7b).
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_TIMEOUT = 15.0


class TelegramSendError(Exception):
    """Raised when a Telegram message cannot be delivered."""


def send_telegram_message(chat_id: str, text: str) -> dict:
    """Send one HTML-formatted message to a Telegram chat.

    Args:
        chat_id: the target chat (bound by the connect flow in the next step).
        text: message body in Telegram-HTML, e.g. from render_telegram_brief.

    Returns:
        The Bot API `result` object on success (the sent Message).

    Raises:
        TelegramSendError: missing token, transport failure, or ok=false.
    """
    token = get_settings().telegram_bot_token
    if not token:
        raise TelegramSendError(
            "TELEGRAM_BOT_TOKEN is not configured; cannot send Telegram messages."
        )

    url = f"{_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise TelegramSendError(f"Telegram request failed: {exc}") from exc

    try:
        body = resp.json()
    except ValueError as exc:
        raise TelegramSendError(
            f"Telegram returned non-JSON (HTTP {resp.status_code})."
        ) from exc

    # The Bot API always answers 200 with an {"ok": bool} envelope; failures
    # carry a human-readable `description` (e.g. "chat not found", "bot was
    # blocked by the user"). Normalize both transport and API errors to one type.
    if not body.get("ok"):
        desc = body.get("description", "unknown error")
        raise TelegramSendError(f"Telegram API error (HTTP {resp.status_code}): {desc}")

    return body["result"]


def get_updates(limit: int = 100) -> list[dict]:
    """Fetch pending updates for the bot — the RECEIVE direction (pattern #4).

    Used by the connect flow to discover the chat_id of whoever just messaged
    the bot: a one-shot pull, no webhook and no long-poll loop. Returns the raw
    `result` list (each item an update dict); picking which chat to bind is the
    caller's job, keeping this a thin wrapper.

    Notes on getUpdates semantics:
      - Without an `offset`, this returns all unconfirmed updates and does NOT
        consume them — calling it repeatedly is safe and idempotent.
      - getUpdates and a webhook are mutually exclusive; if a webhook is ever
        set on this bot, getUpdates returns 409. We never set one.
      - Telegram drops updates older than ~24h, so connect right after messaging
        the bot.
    """
    token = get_settings().telegram_bot_token
    if not token:
        raise TelegramSendError("TELEGRAM_BOT_TOKEN is not configured.")

    url = f"{_API_BASE}/bot{token}/getUpdates"
    try:
        resp = httpx.get(url, params={"limit": limit}, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise TelegramSendError(f"Telegram getUpdates failed: {exc}") from exc

    try:
        body = resp.json()
    except ValueError as exc:
        raise TelegramSendError(
            f"Telegram returned non-JSON (HTTP {resp.status_code})."
        ) from exc

    if not body.get("ok"):
        desc = body.get("description", "unknown error")
        raise TelegramSendError(f"Telegram API error (HTTP {resp.status_code}): {desc}")

    return body.get("result", [])

"""
Resend email sender — sends one HTML email (V7).

Single point of contact with the email provider (pattern #4): services never
build email requests inline, they call send_email(). One normalized exception
(EmailSendError) covers a missing key, a transport error, and a Resend 4xx.

Uses Resend's HTTP API directly via httpx rather than the `resend` SDK — one
fewer dependency, and the same client already used by the Telegram wrapper.
Contrast with Telegram: Resend authenticates with an Authorization: Bearer
header (not a token in the URL path) and returns {"id": "..."} on success.

Free-tier note (why FROM_EMAIL defaults to onboarding@resend.dev): until a
domain is verified, Resend only allows sending FROM its default address and
only TO your own account email. Verifying a domain (FROM_EMAIL ->
you@yourdomain) lifts both limits; the default keeps the demo working with no
DNS setup.

Sync def (like the other tools): the V7c dispatcher calls it via
asyncio.to_thread so a blocking POST never sits on the event loop.

Versioning:
    V7: this file (V7b).
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_URL = "https://api.resend.com/emails"
_TIMEOUT = 20.0


class EmailSendError(Exception):
    """Raised when an email cannot be sent."""


def send_email(to: str, subject: str, html: str) -> dict:
    """Send one HTML email via Resend.

    Args:
        to: recipient address (on the free tier, must be your Resend account
            email until a domain is verified).
        subject: email subject line.
        html: full HTML document, e.g. from render_email_html.

    Returns:
        Resend's response dict on success, e.g. {"id": "<email-id>"}.

    Raises:
        EmailSendError: missing key, transport failure, or a Resend 4xx/5xx.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailSendError("RESEND_API_KEY is not configured; cannot send email.")

    payload = {
        "from": settings.from_email,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    headers = {"Authorization": f"Bearer {settings.resend_api_key}"}

    try:
        resp = httpx.post(_API_URL, json=payload, headers=headers, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise EmailSendError(f"Email request failed: {exc}") from exc

    if resp.status_code >= 400:
        # Resend returns a JSON error body with a human-readable `message`
        # (e.g. "You can only send testing emails to your own email address").
        try:
            err = resp.json()
            detail = err.get("message") or err.get("name") or resp.text
        except ValueError:
            detail = resp.text
        raise EmailSendError(f"Resend error (HTTP {resp.status_code}): {detail}")

    return resp.json()

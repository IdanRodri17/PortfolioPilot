"""
Credential verification endpoint (V8).

POST /api/auth/verify   check an email + password against the users table

This is the backend half of V8a auth. NextAuth.js (frontend) runs a Credentials
provider whose authorize() POSTs {email, password} here; on success we return
the user identity, which NextAuth puts into the session JWT. bcrypt verification
stays server-side in Python — the Next process never sees the hash.

Sync `def` like api/portfolio.py and api/delivery.py: a pure DB handler with no
graph await, so FastAPI runs it in the threadpool and the event loop stays free.

Security shape:
    - One opaque 401 ("Invalid email or password") for every failure mode —
      unknown email, no password set, wrong password — so the response can't be
      used to enumerate which emails have accounts.
    - bcrypt.checkpw is constant-time for the compare itself; we accept that a
      missing-user path returns slightly faster (no hash to check). For a
      single-user demo that timing channel is not worth a dummy-hash compare,
      but that's the standard hardening if it ever matters (noted for V9).

Versioning:
    V8: this file (V8a). The hashed_password column on User is seeded out of
        band (psql) for idan_demo; a future signup endpoint would write it.
"""

import logging

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import User
from app.schemas.auth import AuthVerifyRequest, AuthVerifyResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/api/auth/verify",
    response_model=AuthVerifyResponse,
    summary="Verify a user's email + password (called by NextAuth)",
)
def verify_credentials(
    payload: AuthVerifyRequest,
    db: Session = Depends(get_db),
) -> AuthVerifyResponse:
    """Verify credentials and return the user identity, or 401.

    Looks the user up by email (not by id — the login form has the email), then
    bcrypt-checks the supplied password against the stored hash. Every failure
    path collapses to the same 401 so we never reveal whether an email exists.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )

    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not user.hashed_password:
        raise invalid

    try:
        ok = bcrypt.checkpw(
            payload.password.encode("utf-8"),
            user.hashed_password.encode("utf-8"),
        )
    except ValueError:
        # A malformed/garbage hash in the column (e.g. a non-bcrypt string)
        # makes checkpw raise rather than return False. Treat as a failed
        # login, but log it — it signals a bad seed, not a bad password.
        logger.warning("verify_credentials: malformed hash for user %s", user.id)
        raise invalid

    if not ok:
        raise invalid

    # name is nullable on the User model; fall back to the id for the session
    # display name so NextAuth always gets a non-null string.
    return AuthVerifyResponse(
        user_id=user.id,
        name=user.name or user.id,
        email=user.email or payload.email,
    )

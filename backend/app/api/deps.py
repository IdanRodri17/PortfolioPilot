"""
Auth dependencies (V9).

The frontend mints a short-lived HS256 JWT signed with the shared AUTH_SECRET
(see the frontend's /api/token route) and sends it as
`Authorization: Bearer <token>`. These dependencies verify it server-side and
derive the user_id from the *verified token*, not from the request — closing the
V8 gap where the backend trusted a `user_id` query/path param (a raw
`curl ...?user_id=anything` could impersonate any user).

Design (decided per the V8 brief): a SEPARATE plain JWT, not Auth.js's encrypted
(JWE) session cookie. The backend stays decoupled from Auth.js internals and
just verifies a standard HS256 token against the shared secret.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

# auto_error=False so we raise our own 401 (with WWW-Authenticate) rather than
# FastAPI's default 403 when the Authorization header is absent.
_bearer = HTTPBearer(auto_error=False)


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Verify the bearer token and return the authenticated user_id (its `sub`).

    Raises 401 on a missing, malformed, or expired token; 500 if the server has
    no AUTH_SECRET configured (a deployment error, not a client error).
    """
    secret = get_settings().auth_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is not configured on the server.",
        )
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = jwt.decode(credentials.credentials, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject.",
        )
    return sub


def require_owner(user_id: str, current_user: str = Depends(require_user)) -> str:
    """Ownership guard for endpoints keyed by a `user_id` path/query param.

    FastAPI resolves this dependency's `user_id` from the same request the
    endpoint sees (path or query), so an endpoint only needs
    `Depends(require_owner)` to enforce that the caller acts only on their own
    data. 403 on a mismatch.
    """
    if user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own data.",
        )
    return current_user

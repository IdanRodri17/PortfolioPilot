"""
Pydantic boundary models for credential verification (V8).

Validates the inbound body for POST /api/auth/verify and shapes its response.
Like schemas/portfolio.py and schemas/delivery.py, this is decoupled from the
ORM — the wire contract is the source of truth (pattern #5).

On `email: str` (not Pydantic's EmailStr): the rest of the project never pulls
in the `email-validator` package, and RFC-correctness of the address is not
what gates login — the bcrypt check is. A malformed email simply won't match a
row and returns 401, which is the correct outcome anyway. Keeping `str` avoids
a new dependency for no security gain.

Versioning:
    V8: this file (V8a). Consumed by NextAuth's Credentials provider, which
        POSTs {email, password} here and reads back the user identity to put
        in the session token.
"""

from pydantic import BaseModel, Field


class AuthVerifyRequest(BaseModel):
    """Inbound payload for POST /api/auth/verify."""

    email: str = Field(min_length=1, description="The user's login email.")
    password: str = Field(min_length=1, description="The plaintext password to check.")


class AuthVerifyResponse(BaseModel):
    """Outbound identity on a successful credential check.

    This is exactly what NextAuth's authorize() returns into the JWT, so the
    session carries user_id (== users.id) for every downstream API call.
    """

    user_id: str
    name: str
    email: str

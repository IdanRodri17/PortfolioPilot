"""
Pydantic boundary models for the scheduled-delivery preferences API (V7).

These validate the inbound PUT body and shape the GET/PUT response for
/api/delivery-preferences/{user_id}. Like schemas/portfolio.py, they are
decoupled from the SQLAlchemy DeliveryPreference model — the wire contract is
the source of truth for what a valid preference looks like (pattern #5); the
DB just stores whatever passes here.

What this layer enforces (self-contained rules — no DB needed):
  - At least one channel is enabled. A preference with both channels off is
    meaningless (nothing would ever be sent).
  - The cadence carries the parameter it needs: every_n_days -> interval_days,
    weekly -> weekday. daily needs neither. The two parameter fields are
    Optional precisely because each is irrelevant to two of the three cadences.
  - timezone is a real IANA zone name. Validating here means the V7c dispatcher
    can call ZoneInfo(pref.timezone) and trust it — a bad zone is rejected at
    the door, not discovered mid-schedule.

What this layer does NOT enforce (it can't — needs the User row):
  - "A checked channel must have a usable address" (email requires User.email;
    Telegram requires a linked telegram_chat_id). That is a cross-entity rule
    and lives in the endpoint handler (step 3), which has the DB session.

Versioning:
    V7: this file.
"""

from datetime import datetime, time
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The three scheduling rules. String-literal union -> the DB stores it as a
# plain String (matching User.risk_profile); the Literal is the boundary guard.
Cadence = Literal["daily", "every_n_days", "weekly"]


class DeliveryPreferenceRequest(BaseModel):
    """Inbound payload for PUT /api/delivery-preferences/{user_id}.

    Full-replace semantics, like the portfolio upsert: the body describes the
    complete desired preference, not a partial patch.
    """

    deliver_telegram: bool = Field(
        default=False, description="Send the short Telegram brief."
    )
    deliver_email: bool = Field(
        default=False, description="Send the full HTML email report."
    )

    cadence: Cadence = Field(
        description="Scheduling rule: every day, every N days, or weekly."
    )
    interval_days: Optional[int] = Field(
        default=None,
        description="Days between sends. Required iff cadence == 'every_n_days'.",
    )
    weekday: Optional[int] = Field(
        default=None,
        description="Day of week, 0=Mon .. 6=Sun. Required iff cadence == 'weekly'.",
    )

    send_time_local: time = Field(
        description="Local wall-clock send time, e.g. 08:00. Interpreted in `timezone`."
    )
    timezone: str = Field(
        description="IANA timezone name, e.g. 'Asia/Jerusalem'. The send time is "
        "local to this zone; DST is resolved at schedule time, never frozen."
    )

    enabled: bool = Field(
        default=True, description="Master on/off; disabled preferences are never due."
    )

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        """Reject anything ZoneInfo can't resolve.

        On Windows there is no system zoneinfo DB, so this relies on the
        `tzdata` package (in requirements.txt); without it even valid zones
        like 'Asia/Jerusalem' raise ZoneInfoNotFoundError.
        """
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"'{v}' is not a valid IANA timezone name.") from exc
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> "DeliveryPreferenceRequest":
        """Cross-field rules: a usable channel choice and a complete cadence."""
        if not (self.deliver_telegram or self.deliver_email):
            raise ValueError("At least one delivery channel must be enabled.")

        if self.cadence == "every_n_days":
            if self.interval_days is None or self.interval_days < 1:
                raise ValueError("cadence 'every_n_days' requires interval_days >= 1.")
        if self.cadence == "weekly":
            if self.weekday is None or not (0 <= self.weekday <= 6):
                raise ValueError("cadence 'weekly' requires weekday in 0..6 (0=Mon).")
        return self


class DeliveryPreferenceResponse(BaseModel):
    """Outbound payload for GET and PUT.

    Mirrors the stored DeliveryPreference row (from_attributes lets the handler
    build it straight from the ORM object). The cross-entity "is this channel
    actually usable" signals the settings UI needs are added by the handler in
    step 3 — they aren't part of the stored preference itself.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    deliver_telegram: bool
    deliver_email: bool
    cadence: Cadence
    interval_days: Optional[int]
    weekday: Optional[int]
    send_time_local: time
    timezone: str
    enabled: bool
    last_sent_at: Optional[datetime]
    updated_at: datetime

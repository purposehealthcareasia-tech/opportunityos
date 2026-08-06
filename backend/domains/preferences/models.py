from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Any, Literal

SearchIntensity = Literal["low", "medium", "high"]


class PreferencesPayload(BaseModel):
    role_families: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_ok: bool = False
    salary_floor_usd: int | None = Field(default=None, ge=0, description="Private — never shared with employers.")
    search_intensity: SearchIntensity = "medium"
    employer_include: list[str] = Field(default_factory=list)
    employer_exclude: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)
    # Phase 1 §vi (1c) — user-supplied booking URL (Calendly / Cal.com /
    # SavvyCal / etc.). When present AND non-empty, the follow-up + email-
    # route dispatch paths append a one-liner "Book a time: <url>" to the
    # outbound body, and inject it into resume free-text sections that
    # already exist (never invents placement). Must be https.
    booking_url: str | None = Field(default=None, max_length=400)

    @field_validator("booking_url")
    @classmethod
    def _validate_https(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith("https://"):
            raise ValueError("booking_url must be an https:// URL")
        # HttpUrl coerces + validates hostname + scheme.
        HttpUrl(v)  # raises ValidationError on malformed URL
        return v


class PreferencesResponse(BaseModel):
    version: int
    payload: PreferencesPayload
    updated_at: Any


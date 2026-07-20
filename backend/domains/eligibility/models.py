from pydantic import BaseModel, Field
from typing import Any, Literal

EligibilityStatus = Literal[
    "citizen", "permanent_resident", "ead_opt", "stem_opt", "h1b", "tn", "other", "unspecified",
]


class EligibilityPayload(BaseModel):
    status: EligibilityStatus = "unspecified"
    dates: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=2000)


class EligibilityResponse(BaseModel):
    version: int
    status: EligibilityStatus
    dates: dict[str, Any]
    derived_flags: dict[str, bool]
    updated_at: Any
    sealed: bool = True

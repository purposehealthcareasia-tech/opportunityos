from pydantic import BaseModel, Field
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


class PreferencesResponse(BaseModel):
    version: int
    payload: PreferencesPayload
    updated_at: Any

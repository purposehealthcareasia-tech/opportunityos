from pydantic import BaseModel, EmailStr, Field
from typing import Any


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class PublicClaim(BaseModel):
    id: str
    user_id: str
    type: str
    value: Any
    source: dict
    evidence: list
    verification: dict
    confidence: float | None = None
    user_approved: bool
    sensitivity: str
    version: int
    superseded_by: str | None = None

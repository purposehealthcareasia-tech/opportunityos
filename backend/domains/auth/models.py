from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from typing import Optional


class ConsentInput(BaseModel):
    process_career_data: bool = False
    discover_jobs: bool = False
    generate_materials: bool = False
    track_applications: bool = False
    email_me: bool = False


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    consents: ConsentInput
    policy_text_version: str

    @field_validator("password")
    @classmethod
    def _min_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password_too_short")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PublicUser(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str = "user"
    passport_activated: bool = False
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: PublicUser


class UserDoc(BaseModel):
    """Mongo shape for `users`."""
    id: str
    email: EmailStr
    password_hash: str
    name: str
    passport_activated: bool = False
    created_at: datetime

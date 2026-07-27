from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

ScopeName = Literal[
    "process_career_data",
    "discover_jobs",
    "generate_materials",
    "track_applications",
    "email_me",
    "submit_applications",
]


class ConsentRecord(BaseModel):
    id: str
    user_id: str
    scope: ScopeName
    granted: bool
    policy_text_version: str
    ts: datetime
    actor: str  # who caused the change (usually user_id; system-set = "system")
    source: str  # e.g. "signup", "settings", "revoke", "seed"


class ConsentChangeRequest(BaseModel):
    scope: ScopeName
    granted: bool
    policy_text_version: str = Field(min_length=1)


class ConsentStateItem(BaseModel):
    scope: ScopeName
    granted: bool
    policy_text_version: str | None = None
    ts: datetime | None = None


class ConsentStateResponse(BaseModel):
    scopes: list[ConsentStateItem]
    policy_text_version: str

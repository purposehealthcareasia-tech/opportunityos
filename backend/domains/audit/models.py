from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


class AuditLog(BaseModel):
    id: str
    actor: str  # user_id or "system"
    action: str  # e.g. "user.signup", "consent.grant", "consent.revoke", "user.profile_update"
    object_ref: str  # e.g. "user:<id>", "consent:<id>"
    ts: datetime
    meta: dict[str, Any] = Field(default_factory=dict)

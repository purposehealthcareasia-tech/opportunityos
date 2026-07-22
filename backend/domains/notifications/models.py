"""Notification models — subscriptions, preferences, notification history."""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Dict, Optional


class PushKeys(BaseModel):
    p256dh: str = Field(..., min_length=8, max_length=200)
    auth: str = Field(..., min_length=8, max_length=100)


class PushSubscription(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=2048)
    keys: PushKeys


class SubscribeRequest(BaseModel):
    subscription: PushSubscription
    user_agent: Optional[str] = Field(default=None, max_length=400)


class UnsubscribeRequest(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=2048)


class PreferencesUpdate(BaseModel):
    """Per-category boolean opt-in map. Missing keys mean 'no change'."""
    application_updates: Optional[bool] = None
    interviews: Optional[bool] = None
    approvals_expiring: Optional[bool] = None
    receipts: Optional[bool] = None
    support: Optional[bool] = None

    def as_dict(self) -> Dict[str, bool]:
        return {k: v for k, v in self.model_dump().items() if v is not None}

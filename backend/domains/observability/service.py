"""Internal analytics events endpoint (labeled STUB per §C.7).
User-facing endpoint just to record a page-view style event for the admin observability list.
"""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from core.db import get_db
from core.deps import get_current_user
from core.time_utils import utc_now


router = APIRouter(prefix="/api/v1/observability", tags=["observability"])


class EventBody(BaseModel):
    event: str = Field(..., min_length=1, max_length=64)
    properties: dict = Field(default_factory=dict)


@router.post("/event")
async def track_event(body: EventBody, user: dict = Depends(get_current_user)):
    """Append an event to the INTERNAL analytics table (PostHog stand-in, labeled stub)."""
    await get_db().internal_analytics_events.insert_one({
        "id": str(uuid.uuid4()),
        "ts": utc_now(),
        "actor_id": user["id"],
        "event": body.event,
        "properties": body.properties or {},
        "label": "INTERNAL STUB — PostHog equivalent.",
    })
    return {"tracked": True}

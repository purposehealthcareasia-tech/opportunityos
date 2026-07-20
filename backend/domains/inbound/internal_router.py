"""Inbound response webhook — Phase 5 labeled stub.

Gate: same INTERNAL_SERVICE_TOKEN semantics as `/api/internal/jobs/bulk`
(missing→401, wrong→403, not-configured→503; token never logged / returned).

Idempotency: by (user_id, ext_message_id). Replays return the existing outcome.
Source: parsed. Note: this is a stub; there is no real inbound-email pipeline in v0.1.
Testers exercise it directly.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from core.db import get_db
from core.config import settings
from domains.outcomes.service import EVENT_ENUM, _insert_outcome
from domains.audit import service as audit


router = APIRouter(prefix="/api/internal/inbound", tags=["internal:inbound"])


class InboundRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    application_id: str = Field(..., min_length=1)
    event: str = Field(..., min_length=1)
    ext_message_id: str = Field(..., min_length=1)
    note: str | None = Field(default=None, max_length=2000)


async def _check_service_token(
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
):
    expected = settings.INTERNAL_SERVICE_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "internal_service_token_not_configured"},
        )
    if not x_service_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "service_token_missing"},
        )
    if x_service_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "service_token_invalid"},
        )
    return True


@router.post("/response", status_code=201, dependencies=[Depends(_check_service_token)])
async def ingest_inbound_response(req: InboundRequest):
    if req.event not in EVENT_ENUM:
        raise HTTPException(status_code=400, detail={"error": "unknown_event"})
    db = get_db()
    # Verify the application belongs to the user.
    app_row = await db.applications.find_one(
        {"id": req.application_id, "user_id": req.user_id}, {"_id": 0, "id": 1},
    )
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    # Idempotency: replay by (user_id, ext_message_id) — return the existing outcome.
    existing = await db.outcomes.find_one(
        {"user_id": req.user_id, "ext_message_id": req.ext_message_id},
        {"_id": 0},
    )
    if existing:
        return {"outcome": existing, "replay": True}
    outcome = await _insert_outcome(
        user_id=req.user_id, application_id=req.application_id,
        event=req.event, source="parsed",
        note=req.note, ext_message_id=req.ext_message_id,
    )
    await audit.write("system:inbound_webhook", "outcome.parsed",
                      f"application:{req.application_id}",
                      {"event": req.event, "ext_message_id": req.ext_message_id})
    return {"outcome": outcome, "replay": False}

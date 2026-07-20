"""User-facing support ticket creation (spec §C.10). Admin listing lives in domains/admin."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from fastapi.encoders import jsonable_encoder

from core.db import get_db
from core.deps import get_current_user
from core.time_utils import utc_now
from domains.audit import service as audit


router = APIRouter(prefix="/api/v1/support", tags=["support"])


class TicketBody(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=5000)


@router.post("/tickets", status_code=201)
async def create_ticket(body: TicketBody, user: dict = Depends(get_current_user)):
    db = get_db()
    now = utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "email": user.get("email"),
        "subject": body.subject,
        "body": body.body,
        "status": "open",
        "replies": [],
        "created_at": now, "updated_at": now,
    }
    await db.support_tickets.insert_one(doc)
    await audit.write(user["id"], "support.ticket_created", f"ticket:{doc['id']}", {})
    # NOTE: no actual email is sent — labeled stub per spec §C.5.
    return jsonable_encoder(doc)


@router.get("/tickets/mine")
async def list_my_tickets(user: dict = Depends(get_current_user)):
    tix = [t async for t in get_db().support_tickets.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)]
    return {"tickets": jsonable_encoder(tix)}

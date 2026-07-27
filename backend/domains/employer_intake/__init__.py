"""Employer Intake — public unauthenticated intake for employers who want to
connect their ATS (Phase 4 Founder Brief · Item 6).

Rails:
  * Endpoint is PUBLIC (no auth) so an HR/hiring lead can submit a lead
    without an OpportunityOS account. Rate-limited by client IP + a small
    honeypot field to deter automated spam.
  * Never blindly stored: all inbound submissions are recorded in
    `employer_intake_requests` in state="new"; admin surfaces this collection
    read-only via the admin router.
  * NEVER contacts the employer automatically. This is a passive lead
    capture — the founder / support staff decides how to follow up.
  * No PII propagates beyond what the employer typed.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from core.db import get_db
from core.deps import require_role
from core.time_utils import utc_now


router = APIRouter(prefix="/api/v1/employer-intake", tags=["employer_intake"])


THROTTLE_PER_IP_PER_HOUR = 3


class EmployerIntakeRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=150)
    contact_email: str = Field(min_length=3, max_length=200)
    contact_role: str | None = Field(default=None, max_length=150)
    ats_name: str | None = Field(default=None, max_length=100)
    open_roles_count: int | None = Field(default=None, ge=0, le=10_000)
    notes: str | None = Field(default=None, max_length=2000)
    # Simple honeypot — bots will fill it, humans will leave it blank
    website_url_confirm: str | None = Field(default=None, max_length=200)

    @field_validator("contact_email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("invalid_email")
        return v.lower().strip()


def _client_ip(req: Request) -> str:
    """Best-effort. Never used for exclusion beyond the throttle window."""
    xff = req.headers.get("x-forwarded-for") or req.headers.get("x-real-ip")
    if xff:
        return xff.split(",")[0].strip()
    return (req.client.host if req.client else "0.0.0.0") or "0.0.0.0"


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit(payload: EmployerIntakeRequest, request: Request):
    """PUBLIC — no auth. Rate-limited by IP + honeypot."""
    db = get_db()
    ip = _client_ip(request)

    # Honeypot — silently accept but discard
    if payload.website_url_confirm and payload.website_url_confirm.strip():
        # Record it as "suspected_bot" for admin visibility, but respond 201
        await db.employer_intake_requests.insert_one({
            "id": str(uuid.uuid4()),
            "company_name": payload.company_name.strip(),
            "contact_name": payload.contact_name.strip(),
            "contact_email": payload.contact_email,
            "contact_role": (payload.contact_role or "").strip() or None,
            "ats_name": (payload.ats_name or "").strip() or None,
            "open_roles_count": payload.open_roles_count,
            "notes": (payload.notes or "").strip() or None,
            "state": "suspected_bot",
            "ip": ip,
            "created_at": utc_now(),
        })
        return {"ok": True, "id": "silent"}

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    ip_n = await db.employer_intake_requests.count_documents({"ip": ip,
                                                                "created_at": {"$gte": since}})
    if ip_n >= THROTTLE_PER_IP_PER_HOUR:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={
            "error": "employer_intake_ip_throttled",
            "window_hours": 1, "cap": THROTTLE_PER_IP_PER_HOUR,
            "message": "Too many submissions from this network in the last hour.",
        })

    doc = {
        "id": str(uuid.uuid4()),
        "company_name": payload.company_name.strip(),
        "contact_name": payload.contact_name.strip(),
        "contact_email": payload.contact_email,
        "contact_role": (payload.contact_role or "").strip() or None,
        "ats_name": (payload.ats_name or "").strip() or None,
        "open_roles_count": payload.open_roles_count,
        "notes": (payload.notes or "").strip() or None,
        "state": "new",
        "ip": ip,
        "created_at": utc_now(),
    }
    await db.employer_intake_requests.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "id": doc["id"], "state": doc["state"]}


# Admin surface — separate from the public POST
admin_router = APIRouter(prefix="/api/v1/admin/employer-intake",
                          tags=["employer_intake_admin"])


@admin_router.get("")
async def list_intake(user: dict = Depends(require_role("admin"))):
    """Admin/staff read-only listing. state field lets triage move rows
    through new → contacted → connected → declined."""
    rows: list[dict] = []
    async for r in get_db().employer_intake_requests.find({}, {"_id": 0}).sort("created_at", -1).limit(500):
        rows.append(r)
    return {"requests": rows, "total": len(rows)}


class StateUpdate(BaseModel):
    state: str = Field(pattern="^(new|contacted|connected|declined|suspected_bot)$")
    admin_note: str | None = Field(default=None, max_length=1000)


@admin_router.patch("/{intake_id}")
async def update_state(intake_id: str, payload: StateUpdate,
                        user: dict = Depends(require_role("admin"))):
    db = get_db()
    row = await db.employer_intake_requests.find_one({"id": intake_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="intake_row_not_found")
    updates = {"state": payload.state, "updated_at": utc_now()}
    if payload.admin_note:
        updates["admin_note"] = payload.admin_note
        updates["admin_note_by"] = user.get("email")
    await db.employer_intake_requests.update_one({"id": intake_id}, {"$set": updates})
    return {**row, **updates}

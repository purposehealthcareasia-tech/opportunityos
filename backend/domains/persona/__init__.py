"""Persona variants (Phase 3 Founder Brief — truthful multi-persona Passport-based
resumes with per-line approved-claim provenance).

A "persona" is a labeled slice of the candidate's approved claims. For example:
  * "Systems Engineer, Automotive"  → emphasize MBSE / vehicle-systems claims
  * "Software Engineer, Backend"    → emphasize Python / SQL / distributed claims
  * "Warehouse Ops"                 → emphasize forklift / OSHA claims (Lane B)

The persona filters which approved claims flow into resume generation (Phase 4
pipeline). Per-line provenance already exists in Phase 4 (`render_manifest.lines[]`
carries `claim_ids`). This module adds the persona layer on top.

Rails:
  * Personas are USER-owned, no admin surface.
  * Persona rows are versioned (append-only + soft-supersede).
  * Only APPROVED claim IDs can be pinned; unapproved / sealed claim IDs are
    rejected with 400. This preserves the Grounding Law (R4).
  * Consent-gated on `generate_materials` (same as resume tailoring).
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import require_consent
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit


router = APIRouter(prefix="/api/v1/personas", tags=["personas"])


class PersonaCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    focus_role_families: list[str] = Field(default_factory=list, max_length=8)
    priority_claim_ids: list[str] = Field(default_factory=list, max_length=50)
    tagline: str | None = Field(default=None, max_length=280)
    intent: str = Field(default="career",
                         pattern="^(career|income_now|hybrid)$")


async def _validate_claim_ids_owned_and_approved(user_id: str, claim_ids: list[str]) -> list[str]:
    """Return the subset of claim_ids that are approved + owned by the user.
    Any invalid id causes a 400 so the user knows the persona wasn't silently
    trimmed."""
    if not claim_ids:
        return []
    rows = get_db().claims.find(
        {"user_id": user_id, "id": {"$in": claim_ids},
         "status": "approved", "superseded_by": None,
         "sensitivity": {"$ne": "sealed"}},  # Never pin a sealed claim
        {"id": 1, "_id": 0},
    )
    ok = {r["id"] async for r in rows}
    missing = [cid for cid in claim_ids if cid not in ok]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={
            "error": "claim_ids_not_approved_or_missing",
            "invalid_ids": missing,
            "message": "Personas may only pin your own APPROVED, non-sealed claim IDs.",
        })
    return list(ok)


@router.get("")
async def list_personas(user: dict = Depends(require_consent("generate_materials"))):
    rows: list[dict] = []
    async for r in get_db().personas.find({"user_id": user["id"], "superseded_by": None},
                                            {"_id": 0}).sort("created_at", -1):
        rows.append(r)
    return {"personas": rows, "total": len(rows)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_persona(req: PersonaCreate,
                          user: dict = Depends(require_consent("generate_materials"))):
    approved_ids = await _validate_claim_ids_owned_and_approved(user["id"], req.priority_claim_ids)
    now = utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "label": req.label.strip(),
        "focus_role_families": [x.strip() for x in req.focus_role_families if x.strip()],
        "priority_claim_ids": approved_ids,
        "tagline": (req.tagline or "").strip() or None,
        "intent": req.intent,
        "version": 1,
        "superseded_by": None,
        "created_at": now,
        "updated_at": now,
    }
    await get_db().personas.insert_one(doc)
    await audit.write(user["id"], "persona.create", f"persona:{doc['id']}",
                       {"label": doc["label"], "intent": doc["intent"]})
    doc.pop("_id", None)
    return doc


@router.get("/{persona_id}")
async def get_persona(persona_id: str,
                       user: dict = Depends(require_consent("generate_materials"))):
    row = await get_db().personas.find_one({"id": persona_id, "user_id": user["id"]},
                                             {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="persona_not_found")
    return row


class PersonaPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    focus_role_families: list[str] | None = Field(default=None, max_length=8)
    priority_claim_ids: list[str] | None = Field(default=None, max_length=50)
    tagline: str | None = Field(default=None, max_length=280)
    intent: str | None = Field(default=None, pattern="^(career|income_now|hybrid)$")


@router.patch("/{persona_id}")
async def update_persona(persona_id: str, req: PersonaPatch,
                          user: dict = Depends(require_consent("generate_materials"))):
    """Append-only edit — creates a v+1 row and marks the previous version as
    superseded so history is preserved."""
    db = get_db()
    prev = await db.personas.find_one({"id": persona_id, "user_id": user["id"],
                                         "superseded_by": None},
                                        {"_id": 0})
    if not prev:
        raise HTTPException(status_code=404, detail="persona_not_found")
    new_id = str(uuid.uuid4())
    approved_ids = prev["priority_claim_ids"]
    if req.priority_claim_ids is not None:
        approved_ids = await _validate_claim_ids_owned_and_approved(user["id"], req.priority_claim_ids)
    now = utc_now()
    doc = {
        **prev,
        "id": new_id,
        "label": (req.label or prev["label"]).strip(),
        "focus_role_families": ([x.strip() for x in req.focus_role_families if x.strip()]
                                  if req.focus_role_families is not None
                                  else prev["focus_role_families"]),
        "priority_claim_ids": approved_ids,
        "tagline": (req.tagline if req.tagline is not None else prev.get("tagline")),
        "intent": req.intent or prev["intent"],
        "version": (prev.get("version") or 1) + 1,
        "superseded_by": None,
        "updated_at": now,
        "created_at": prev["created_at"],  # keep origin
    }
    await db.personas.insert_one(doc)
    await db.personas.update_one({"id": prev["id"]}, {"$set": {"superseded_by": new_id}})
    await audit.write(user["id"], "persona.update", f"persona:{new_id}",
                       {"previous_id": prev["id"], "label": doc["label"]})
    doc.pop("_id", None)
    return doc


async def approved_claims_for_persona(user_id: str, persona_id: Optional[str]) -> list[dict]:
    """Helper for Phase 4 resume generation. Returns approved claims filtered /
    reordered by the persona's priority list (if provided). If persona_id is
    None, returns all approved claims (existing default behavior).
    """
    db = get_db()
    all_approved = []
    async for c in db.claims.find({"user_id": user_id, "status": "approved",
                                     "superseded_by": None},
                                     {"_id": 0}):
        all_approved.append(c)
    if not persona_id:
        return all_approved
    persona = await db.personas.find_one({"id": persona_id, "user_id": user_id,
                                            "superseded_by": None},
                                           {"_id": 0})
    if not persona:
        return all_approved
    priority = persona.get("priority_claim_ids") or []
    if not priority:
        return all_approved
    priority_set = set(priority)
    prio_rows = [c for c in all_approved if c.get("id") in priority_set]
    rest = [c for c in all_approved if c.get("id") not in priority_set]
    # Preserve priority ordering as declared by the persona
    prio_rows.sort(key=lambda c: priority.index(c["id"]) if c.get("id") in priority_set else 999)
    return prio_rows + rest

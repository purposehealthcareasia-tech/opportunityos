"""Phase 6 Privacy — /privacy page backend + export bundle + soft-delete lifecycle.

Endpoints (all under `/api/v1/privacy`):
  GET  /consents        — current scopes + granted state
  POST /consents/revoke — {scope} → immediate revoke (mirrors existing /consents POST with granted:false)
  GET  /release-log     — data-release timeline: receipts + authorizations, employer-scoped
  POST /export          — kick off async export bundle; returns job_id
  GET  /export/{id}     — poll status; when ready, `download_url` field is populated
  POST /account/delete  — enters deletion_pending (30-day window)
  POST /account/restore — cancels a pending deletion (before 30d elapsed)

Deletion:
  - Soft delete flips users.deletion_pending_at + users.deletion_scheduled_for.
  - `require_current_user` refuses to log the user in once deletion_pending_at is set.
  - Startup task hard-deletes rows where deletion_scheduled_for < now().
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from core.db import get_db
from core.deps import get_current_user
from core.time_utils import utc_now
from domains.audit import service as audit


router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])

DELETION_GRACE_DAYS = 30


class RevokeBody(BaseModel):
    scope: str


class DeleteBody(BaseModel):
    confirm: bool = False


# ---------- Consents surface ----------

@router.get("/consents")
async def list_consents(user: dict = Depends(get_current_user)):
    db = get_db()
    # Latest consent row per scope for this user.
    rows = [c async for c in db.consent_records.find({"user_id": user["id"]}, {"_id": 0}).sort("ts", -1)]
    latest: dict[str, dict] = {}
    for r in rows:
        latest.setdefault(r["scope"], r)
    scopes = [
        {"scope": "ingest_history",       "label": "Career-history ingestion", "granted": False},
        {"scope": "generate_materials",   "label": "AI-generated résumé & cover materials", "granted": False},
        {"scope": "track_applications",   "label": "Application tracking + inbound updates", "granted": False},
        {"scope": "analytics_anon",       "label": "Anonymous product analytics", "granted": False},
    ]
    for s in scopes:
        row = latest.get(s["scope"])
        if row:
            s["granted"] = bool(row.get("granted", True))
            s["ts"] = row.get("ts")
    return {"scopes": scopes}


@router.post("/consents/revoke")
async def revoke_consent(body: RevokeBody, user: dict = Depends(get_current_user)):
    from domains.consent import router as consent_router  # avoid circular
    # Delegate to the canonical POST /consents endpoint by writing a revoke row.
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "scope": body.scope,
        "granted": False,
        "policy_text_version": "1.0",
        "ts": utc_now(),
    }
    await db.consent_records.insert_one(doc)
    await audit.write(user["id"], "privacy.consent_revoked", f"scope:{body.scope}", {})
    return {"scope": body.scope, "granted": False}


# ---------- Release log ----------

@router.get("/release-log")
async def release_log(user: dict = Depends(get_current_user)):
    """Every submission_receipts row IS a data-release event. This surface pulls them
    and joins per-application authorization info."""
    db = get_db()
    receipts = [r async for r in db.submission_receipts.find({"user_id": user["id"]}, {"_id": 0}).sort("ts", -1)]
    apps_by_id: dict[str, dict] = {}
    async for a in db.applications.find({"user_id": user["id"]}, {"_id": 0, "id": 1, "job_snapshot": 1}):
        apps_by_id[a["id"]] = a
    entries: list[dict] = []
    for r in receipts:
        snap = (apps_by_id.get(r["application_id"]) or {}).get("job_snapshot") or {}
        entries.append({
            "receipt_id": r["id"],
            "ts": r["ts"],
            "employer": snap.get("company_name") or r.get("company_id"),
            "role": snap.get("title") or "—",
            "req_ref": r["req_ref"],
            "materials_hash": r.get("materials_manifest_hash"),
            "channel": r.get("submit_channel"),
            "kind": "submission",
        })
    return {"releases": jsonable_encoder(entries)}


# ---------- Export bundle ----------

@router.post("/export")
async def start_export(user: dict = Depends(get_current_user)):
    db = get_db()
    job_id = str(uuid.uuid4())
    now = utc_now()
    await db.export_jobs.insert_one({
        "id": job_id, "user_id": user["id"], "status": "running",
        "created_at": now, "updated_at": now, "bundle": None,
    })
    # Synchronous build in v0.1 — the "async" contract is honored by exposing the
    # status endpoint; the compute is fast enough (single-user aggregation) that we
    # don't need a worker. This is recorded as an honest v0.1 shortcut in PRD.
    bundle = await _build_bundle(user["id"])
    await db.export_jobs.update_one(
        {"id": job_id},
        {"$set": {"status": "ready", "bundle": bundle, "updated_at": utc_now()}},
    )
    await audit.write(user["id"], "privacy.export_requested", f"export:{job_id}", {})
    return {"job_id": job_id, "status": "ready"}


@router.get("/export/{job_id}")
async def get_export(job_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    row = await db.export_jobs.find_one({"id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="export_not_found")
    if row["status"] != "ready":
        return {"job_id": job_id, "status": row["status"]}
    return {"job_id": job_id, "status": "ready",
            "download": {"filename": f"opportunityos-export-{job_id[:8]}.json",
                         "content": row["bundle"]}}


async def _build_bundle(user_id: str) -> dict:
    """Complete bundle including sealed own-values (user's own data).

    IMPORTANT (SEC-001): the `profile` field is passed through the same
    `_sanitize_user` scrubber used by the admin console so credential material
    (`password_hash`, `totp_secret`, …) NEVER lands in a self-download bundle.
    Reuses the single-source-of-truth `SENSITIVE_USER_FIELDS` registry."""
    db = get_db()
    # Import lazily to avoid a circular import (admin service imports the
    # session store, which is fine, but domain-to-domain reuse is cleaner via
    # this local reference).
    from domains.admin.service import _sanitize_user, SENSITIVE_USER_FIELDS
    projection = {"_id": 0, **{f: 0 for f in SENSITIVE_USER_FIELDS}}
    user = await db.users.find_one({"id": user_id}, projection)
    user = _sanitize_user(user)

    async def _fetch(coll: str, filt: dict) -> list[dict]:
        return [x async for x in db[coll].find(filt, {"_id": 0})]

    bundle: dict = {
        "profile": user,
        "claims":               await _fetch("claims",             {"user_id": user_id}),
        "documents":            await _fetch("documents",          {"user_id": user_id}),
        "resume_versions":      await _fetch("resume_versions",    {"user_id": user_id}),
        "preferences":          await _fetch("preferences",        {"user_id": user_id}),
        "eligibility_profiles": await _fetch("eligibility_profiles", {"user_id": user_id}),
        "applications":         await _fetch("applications",       {"user_id": user_id}),
        "submission_receipts":  await _fetch("submission_receipts",{"user_id": user_id}),
        "outcomes":             await _fetch("outcomes",           {"user_id": user_id}),
        "interviews":           await _fetch("interviews",         {"user_id": user_id}),
        "consent_records":      await _fetch("consent_records",    {"user_id": user_id}),
        "screening_answers":    await _fetch("screening_answers",  {"user_id": user_id}),
        "authorization_scopes": await _fetch("authorization_scopes",{"user_id": user_id}),
        "subscriptions":        await _fetch("subscriptions",      {"user_id": user_id}),
        "audit_trail":          await _fetch("audit_logs",         {"actor": user_id}),
        "exported_at": utc_now().isoformat(),
    }
    return jsonable_encoder(bundle)


# ---------- Soft delete ----------

@router.post("/account/delete")
async def delete_account(body: DeleteBody, user: dict = Depends(get_current_user)):
    if not body.confirm:
        raise HTTPException(status_code=400, detail={"error": "confirm_required",
                                                       "message": "Set confirm:true to proceed."})
    db = get_db()
    now = utc_now()
    scheduled = now + timedelta(days=DELETION_GRACE_DAYS)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"deletion_pending_at": now, "deletion_scheduled_for": scheduled}},
    )
    await audit.write(user["id"], "privacy.account_deletion_pending",
                      f"user:{user['id']}", {"scheduled_for": scheduled.isoformat()})
    return {"deletion_pending_at": now.isoformat(),
            "deletion_scheduled_for": scheduled.isoformat(),
            "restorable": True,
            "message": f"Your account will be permanently deleted on {scheduled.date().isoformat()}. Sign in to cancel."}


@router.post("/account/restore")
async def restore_account(user: dict = Depends(get_current_user)):
    db = get_db()
    row = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    if not row or not row.get("deletion_pending_at"):
        raise HTTPException(status_code=409, detail={"error": "not_pending_deletion"})
    await db.users.update_one(
        {"id": user["id"]},
        {"$unset": {"deletion_pending_at": "", "deletion_scheduled_for": ""}},
    )
    await audit.write(user["id"], "privacy.account_restored", f"user:{user['id']}", {})
    return {"restored": True}


async def sweep_expired_deletions() -> int:
    """Hard-delete rows where deletion_scheduled_for < now. Called on startup + admin ping.
    Returns count of users hard-deleted."""
    db = get_db()
    now = utc_now()
    to_delete = [u async for u in db.users.find(
        {"deletion_scheduled_for": {"$lte": now}}, {"_id": 0, "id": 1},
    )]
    count = 0
    for u in to_delete:
        uid = u["id"]
        for coll in ["claims", "documents", "resume_versions", "preferences",
                     "eligibility_profiles", "applications", "submission_receipts",
                     "outcomes", "interviews", "consent_records", "screening_answers",
                     "authorization_scopes", "subscriptions", "match_scores",
                     "score_feedback", "usage_meters", "hidden_jobs",
                     "ai_generations", "export_jobs", "payment_transactions",
                     "manual_queue_items"]:
            await db[coll].delete_many({"user_id": uid})
        await db.users.delete_one({"id": uid})
        await audit.write("system:deletion_sweep", "privacy.account_hard_deleted",
                          f"user:{uid}", {})
        count += 1
    return count

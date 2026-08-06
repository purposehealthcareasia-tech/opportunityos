"""Phase 1 §v (1b) — Apply Wave + Spectrum Builder.

RULE (Founder directive 2026-08-06):
  ONE batch authorization queues all eligible spectrum jobs into Submit
  Sprint. Eligible = passing THREE hard gates
  (work_auth / licensure / location_onsite), rolling 30-day per-employer
  cap NEVER bypassed, deduped against existing non-closed applications.

  Standing Wave: when the user turns it on, subsequent apply-at-birth
  ticks re-run the wave scope against new arrivals only, again respecting
  the cap. `wave_authorizations` is append-only and stores a snapshot of
  the user's consent scopes at authorize time.

Consent gate: `submit_applications` (Phase 4 dispatch-authorization
scope). The cap check runs BEFORE any shortlist attempt; a wave never
"queues then drops" — it decides first.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import require_consent
from core.time_utils import utc_now
from domains.applications import service as apps_svc
from domains.audit import service as audit
from domains.jobs import repository as jobs_repo
from services import employer_cap as cap_svc
from services import gate_engine
from services.employer_cap import _employer_key as _emp_key


router = APIRouter(prefix="/api/v1/wave", tags=["wave"])


# ------------------------------ Data models ------------------------------ #

class WaveScope(BaseModel):
    """Spectrum filter for one authorization."""
    lane: Optional[str] = Field(default=None, pattern="^(career|income_now)$")
    within_mi: Optional[int] = Field(default=None, ge=0, le=500)
    family: Optional[str] = Field(default=None, max_length=64)
    cap: int = Field(default=25, ge=1, le=250,
                       description="Hard ceiling on jobs queued this wave.")
    standing_wave: bool = Field(default=False,
                                    description="Auto-queue future arrivals matching this scope on AAB ticks.")


# ------------------------------ Helpers ---------------------------------- #

async def _snapshot_consents(user_id: str) -> dict:
    """Return `{scope → status}` for the user AT authorization time.
    Stored on the wave_authorizations row so audits can reconstruct what
    the user had granted when they clicked."""
    db = get_db()
    out: dict[str, str] = {}
    async for r in db.consent_records.find(
        {"user_id": user_id}, {"_id": 0, "scope": 1, "status": 1, "granted_at": 1, "revoked_at": 1},
    ):
        # Latest wins — collection is append-only in Phase 5; we
        # tolerate either shape.
        out[r["scope"]] = r.get("status") or (
            "granted" if r.get("granted_at") and not r.get("revoked_at") else "revoked")
    return out


def _matches_scope(job: dict, scope: WaveScope) -> bool:
    """Additive filter: return True only when the job matches EVERY
    filter set on the scope."""
    if scope.lane and job.get("lane") != scope.lane:
        return False
    if scope.within_mi is not None:
        d = job.get("distance_from_phoenix_mi")
        if not isinstance(d, (int, float)) or d > scope.within_mi:
            return False
    if scope.family:
        fam = str(job.get("taxonomy_family") or "").strip().lower()
        if fam != scope.family.strip().lower():
            return False
    return True


async def _enumerate_eligible(user_id: str, scope: WaveScope,
                                 candidate_ids: Optional[list[str]] = None
                                 ) -> tuple[list[dict], dict]:
    """Return (eligible_jobs, breakdown).

    breakdown accounts for every candidate: `total_scanned`, plus buckets
    `blocked_hard_gate`, `blocked_cap`, `blocked_duplicate`, `blocked_scope`.
    """
    ctx = await gate_engine.build_context(user_id)
    if candidate_ids is not None:
        candidates: list[dict] = []
        for j in await jobs_repo.list_live():
            if j["id"] in set(candidate_ids):
                candidates.append(j)
    else:
        candidates = await jobs_repo.list_live()

    breakdown = {
        "total_scanned": len(candidates),
        "blocked_scope": 0,
        "blocked_hard_gate": 0,
        "blocked_cap": 0,
        "blocked_duplicate": 0,
    }
    eligible: list[dict] = []
    seen_emp_counts: dict[str, int] = {}
    for job in candidates:
        if not _matches_scope(job, scope):
            breakdown["blocked_scope"] += 1
            continue
        gate = gate_engine.evaluate(ctx, job)
        if not gate["pass_all"]:
            breakdown["blocked_hard_gate"] += 1
            continue
        # duplicate check via ctx.existing_applications (built above)
        if job["id"] in (ctx.get("existing_applications") or set()):
            breakdown["blocked_duplicate"] += 1
            continue
        # employer cap — count wave-queued so far in this pass too
        cap_info = await cap_svc.check_cap(user_id, job)
        emp_key = _emp_key(job) or ""
        wave_already = seen_emp_counts.get(emp_key, 0)
        # cap_info.remaining is remaining after already-open apps. The wave
        # itself also consumes cap slots — respect that in this pass.
        remaining = int(cap_info.get("remaining") or 0)
        if not cap_info.get("ok") or wave_already >= remaining:
            breakdown["blocked_cap"] += 1
            continue
        eligible.append(job)
        seen_emp_counts[emp_key] = wave_already + 1
        if len(eligible) >= scope.cap:
            break
    return eligible, breakdown


async def _persist_authorization(user_id: str, scope: WaveScope,
                                    breakdown: dict, queued_app_ids: list[str],
                                    blocked_at_shortlist: list[dict],
                                    consents_snapshot: dict,
                                    triggered_by: str = "user_batch") -> str:
    """Insert one wave_authorizations row. Returns the wave id."""
    wid = str(uuid.uuid4())
    now = utc_now()
    row = {
        "id": wid,
        "user_id": user_id,
        "authorized_at": now,
        "triggered_by": triggered_by,
        "scope": scope.model_dump(),
        "consents_snapshot": consents_snapshot,
        "breakdown": breakdown,
        "queued_app_ids": queued_app_ids,
        "queued_count": len(queued_app_ids),
        "blocked_at_shortlist": blocked_at_shortlist,
    }
    await get_db().wave_authorizations.insert_one(row)
    return wid


# ------------------------------ Endpoints -------------------------------- #

@router.post("/authorize", status_code=201)
async def authorize_wave(scope: WaveScope,
                            user: dict = Depends(require_consent("submit_applications"))):
    """Batch-authorize a spectrum of eligible jobs into Submit Sprint.

    Contract:
      * All eligible jobs are shortlisted in one pass.
      * Cap is respected (never bypassed) even for the batch itself.
      * A `wave_authorizations` row is written before the endpoint returns.
      * Consent scopes are snapshotted onto the row for audit.
    """
    user_id = user["id"]
    consents = await _snapshot_consents(user_id)
    eligible, breakdown = await _enumerate_eligible(user_id, scope)

    queued: list[dict] = []
    shortlist_blocked: list[dict] = []
    for job in eligible:
        try:
            app_row = await apps_svc.shortlist(user_id, job)
            queued.append(app_row)
        except apps_svc.DuplicateApplication:
            shortlist_blocked.append({"job_id": job["id"], "reason": "duplicate"})
        except apps_svc.EmployerCapReached as e:
            shortlist_blocked.append({"job_id": job["id"], "reason": "employer_cap_reached",
                                        "cap_info": e.cap_info})

    wid = await _persist_authorization(
        user_id, scope, breakdown,
        queued_app_ids=[q["id"] for q in queued],
        blocked_at_shortlist=shortlist_blocked,
        consents_snapshot=consents,
        triggered_by="user_batch",
    )

    # If Standing Wave, persist the scope on the user prefs sidecar so
    # AAB ticks can consult it. Idempotent — overwrites any prior standing
    # scope for this user.
    if scope.standing_wave:
        await get_db().standing_waves.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "scope": scope.model_dump(),
                       "created_at": utc_now(), "last_authorization_id": wid,
                       "active": True}},
            upsert=True,
        )

    await audit.write(user_id, "wave.authorize", f"wave:{wid}", {
        "queued": len(queued),
        "breakdown": breakdown,
        "standing_wave": scope.standing_wave,
    })
    return {
        "id": wid,
        "queued_count": len(queued),
        "queued_app_ids": [q["id"] for q in queued],
        "breakdown": breakdown,
        "blocked_at_shortlist": shortlist_blocked,
        "standing_wave": bool(scope.standing_wave),
        "consents_snapshot": consents,
    }


@router.get("/authorizations")
async def list_authorizations(user: dict = Depends(require_consent("submit_applications"))):
    """List past wave authorizations for this user, most recent first."""
    db = get_db()
    rows = []
    async for r in db.wave_authorizations.find(
        {"user_id": user["id"]}, {"_id": 0}).sort("authorized_at", -1).limit(50):
        rows.append(r)
    return {"authorizations": rows}


@router.get("/standing")
async def get_standing(user: dict = Depends(require_consent("submit_applications"))):
    """Return the user's active Standing Wave scope, if any."""
    row = await get_db().standing_waves.find_one(
        {"user_id": user["id"], "active": True}, {"_id": 0})
    return {"standing": row}


@router.delete("/standing", status_code=204)
async def deactivate_standing(user: dict = Depends(require_consent("submit_applications"))):
    """Turn off Standing Wave. Idempotent — no error if none was active."""
    await get_db().standing_waves.update_one(
        {"user_id": user["id"], "active": True},
        {"$set": {"active": False, "deactivated_at": utc_now()}},
    )
    await audit.write(user["id"], "wave.standing.deactivate", f"user:{user['id']}", {})
    return None


# ------------------------ Standing-Wave AAB hook ------------------------- #

async def run_standing_waves_after_aab_tick(new_job_ids: list[str]) -> dict:
    """Called from `services/apply_at_birth.tick` after it ingests new
    postings. For every active Standing Wave, re-run the scope over the
    new-arrival subset and queue matches. Cap is respected identically to
    the manual authorize path (same helper).

    Returns a summary; callers persist as needed.
    """
    if not new_job_ids:
        return {"users_processed": 0, "queued_total": 0}
    db = get_db()
    users_processed = 0
    queued_total = 0
    async for sw in db.standing_waves.find({"active": True}, {"_id": 0}):
        user_id = sw["user_id"]
        scope = WaveScope(**(sw.get("scope") or {}))
        eligible, breakdown = await _enumerate_eligible(user_id, scope,
                                                          candidate_ids=new_job_ids)
        queued: list[dict] = []
        shortlist_blocked: list[dict] = []
        for job in eligible:
            try:
                app_row = await apps_svc.shortlist(user_id, job)
                queued.append(app_row)
            except apps_svc.DuplicateApplication:
                shortlist_blocked.append({"job_id": job["id"], "reason": "duplicate"})
            except apps_svc.EmployerCapReached as e:
                shortlist_blocked.append({"job_id": job["id"], "reason": "employer_cap_reached",
                                            "cap_info": e.cap_info})
        consents = await _snapshot_consents(user_id)
        wid = await _persist_authorization(
            user_id, scope, breakdown,
            queued_app_ids=[q["id"] for q in queued],
            blocked_at_shortlist=shortlist_blocked,
            consents_snapshot=consents,
            triggered_by="standing_wave_aab_tick",
        )
        await audit.write(user_id, "wave.standing.tick", f"wave:{wid}", {
            "queued": len(queued), "new_arrivals": len(new_job_ids),
        })
        users_processed += 1
        queued_total += len(queued)
    return {"users_processed": users_processed, "queued_total": queued_total}

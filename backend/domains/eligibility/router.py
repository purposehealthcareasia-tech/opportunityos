import uuid
from fastapi import APIRouter, Depends
from core.deps import require_consent, get_current_user
from core.time_utils import utc_now
from services.gate_engine import derive_flags, evaluate
from domains.eligibility.models import EligibilityPayload
from domains.eligibility import repository as repo
from domains.audit import service as audit

router = APIRouter(prefix="/api/v1/eligibility", tags=["eligibility"])


def _serialize(doc: dict | None) -> dict:
    if not doc:
        return {
            "version": 0,
            "status": "unspecified",
            "dates": {},
            "derived_flags": derive_flags("unspecified"),
            "updated_at": None,
            "sealed": True,
        }
    return {
        "version": doc["version"],
        "status": doc["status"],
        "dates": doc.get("dates") or {},
        "derived_flags": doc.get("derived_flags") or derive_flags(doc["status"]),
        "updated_at": doc.get("updated_at"),
        "sealed": True,
    }


@router.get("/me")
async def get_my_eligibility(user: dict = Depends(get_current_user)):
    """Owner-only read. Eligibility profiles are sealed — no admin/support endpoint exists in Phase 2."""
    latest = await repo.latest_for_user(user["id"])
    return _serialize(latest)


@router.post("", status_code=201)
async def save_my_eligibility(
    payload: EligibilityPayload,
    user: dict = Depends(require_consent("process_career_data")),
):
    version = await repo.next_version(user["id"])
    derived = derive_flags(payload.status)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "version": version,
        "status": payload.status,
        "dates": payload.dates,
        "notes": payload.notes,
        "derived_flags": derived,
        "sensitivity": "sealed",
        "updated_at": utc_now(),
    }
    await repo.insert(doc)
    await audit.write(user["id"], "eligibility.save", f"user:{user['id']}", {"version": version, "status": payload.status})
    return _serialize(doc)


@router.get("/coverage-preview")
async def coverage_preview(user: dict = Depends(require_consent("discover_jobs"))):
    """Runs the gate engine against every live job and returns a coverage summary.

    Requires the user to have declared their eligibility AND granted the discover_jobs scope.
    Sample jobs are included in the sample_pass_count for observability but do NOT count in
    production cohorts (they're clearly badged is_sample:true in the response).
    """
    latest = await repo.latest_for_user(user["id"])
    profile = {"status": latest.get("status") if latest else "unspecified"}

    jobs = await repo.live_jobs()
    total = len(jobs)
    passing: list[dict] = []
    excluded_by_reason: dict[str, int] = {}
    unknown_by_reason: dict[str, int] = {}
    sample_pass = 0
    real_pass = 0

    per_job: list[dict] = []
    for j in jobs:
        result = evaluate(profile, j)
        entry = {
            "job_id": j["id"],
            "canonical_key": j.get("canonical_key"),
            "title": j.get("title"),
            "is_sample": bool(j.get("is_sample")),
            "pass_all": result["pass_all"],
            "fail_reasons": result["fail_reasons"],
            "unknown_reasons": result["unknown_reasons"],
            "gates": result["gates"],
        }
        per_job.append(entry)
        if result["pass_all"]:
            passing.append(entry)
            if j.get("is_sample"):
                sample_pass += 1
            else:
                real_pass += 1
        for reason in result["fail_reasons"]:
            excluded_by_reason[reason] = excluded_by_reason.get(reason, 0) + 1
        for reason in result["unknown_reasons"]:
            unknown_by_reason[reason] = unknown_by_reason.get(reason, 0) + 1

    return {
        "profile": {
            "status": profile["status"],
            "derived_flags": derive_flags(profile["status"]),
        },
        "totals": {
            "live_jobs": total,
            "passing": len(passing),
            "sample_passing": sample_pass,
            "real_passing": real_pass,
            "excluded_by_reason": excluded_by_reason,
            "unknown_by_reason": unknown_by_reason,
        },
        "jobs": per_job,
        "disclaimer": "This is not legal advice. Eligibility rules encoded here are heuristics based on employer listings.",
    }

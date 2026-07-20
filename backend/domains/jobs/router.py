import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.deps import get_current_user, require_consent
from core.db import get_db
from services.gate_engine import build_context, evaluate
from services.scoring import score as score_job, WEIGHTS_VERSION
from domains.jobs.models import ImportRequest, ResolveOriginRequest, HideRequest
from domains.jobs import service as jobs_svc, repository as jobs_repo
from domains.applications import service as apps_svc
from domains.audit import service as audit

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _shape_job_card(job: dict, score_row: dict | None) -> dict:
    from services.gate_engine import _is_stale
    stale = _is_stale(job)
    effective_status = "stale" if stale and job.get("status") == "live" else job.get("status")
    return {
        "id": job["id"],
        "canonical_key": job.get("canonical_key"),
        "title": job.get("title"),
        "company_name": job.get("company_name"),
        "company_domain": job.get("company_domain"),
        "geo": job.get("geo"),
        "comp": job.get("comp"),
        "taxonomy_family": job.get("taxonomy_family"),
        "apply_method": job.get("apply_method"),
        "status": effective_status,
        "is_sample": bool(job.get("is_sample")),
        "last_verified": job.get("last_verified"),
        "needs_origin": bool(job.get("needs_origin")),
        "score": (score_row or {}).get("score"),
        "confidence": (score_row or {}).get("confidence"),
        "weights_version": (score_row or {}).get("weights_version"),
    }


@router.get("/feed")
async def feed(user: dict = Depends(require_consent("discover_jobs"))):
    # Also require the passport to be activated. We surface an honest error the UI can render as a
    # passport-activation gate (distinct from consent gate).
    fresh = await get_db().users.find_one({"id": user["id"]}, {"passport_activated": 1, "_id": 0})
    if not (fresh and fresh.get("passport_activated")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "passport_not_activated", "hint": "Activate your Passport in /passport before browsing the feed."})

    ctx = await build_context(user["id"])
    hidden = ctx.get("hidden_job_ids") or set()
    jobs = [j for j in await jobs_repo.list_live() if j["id"] not in hidden]

    passing: list[dict] = []
    excluded: list[dict] = []
    scored_new_count = 0
    from domains.match_scores import service as ms
    from domains.usage_meters import service as um

    for job in jobs:
        gate = evaluate(ctx, job)
        if gate["pass_all"]:
            s = score_job(ctx, job, gate)
            was_new = await ms.upsert(user_id=user["id"], job_id=job["id"], score=s, gates=gate)
            if was_new:
                scored_new_count += 1
            passing.append({
                **_shape_job_card(job, s),
                "gates": gate["gates"],
                "top_reasons": [rc for rc in s["reason_codes"] if rc["weight_applied"] > 0][:2],
                "route": apps_svc.route_decision(job),
            })
        else:
            excluded.append({
                "id": job["id"],
                "title": job.get("title"),
                "company_name": job.get("company_name"),
                "is_sample": bool(job.get("is_sample")),
                "canonical_key": job.get("canonical_key"),
                "fail_reasons": gate["fail_reasons"],
                "unknown_reasons": gate["unknown_reasons"],
            })
    if scored_new_count:
        await um.increment_jobs_processed(user["id"], scored_new_count)

    passing.sort(key=lambda x: (x.get("score") or 0), reverse=True)
    return {
        "weights_version": WEIGHTS_VERSION,
        "passing": passing,
        "excluded": excluded,
        "totals": {"passing": len(passing), "excluded": len(excluded)},
    }


@router.get("/{job_id}")
async def job_detail(job_id: str, user: dict = Depends(require_consent("discover_jobs"))):
    job = await jobs_repo.by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    ctx = await build_context(user["id"])
    gate = evaluate(ctx, job)
    s = None
    if gate["pass_all"]:
        s = score_job(ctx, job, gate)
        from domains.match_scores import service as ms
        await ms.upsert(user_id=user["id"], job_id=job_id, score=s, gates=gate)

    # Have/gap for skills using approved skill claims (never unapproved)
    req_skills = [str(x).lower() for x in ((job.get("requirements") or {}).get("skills_required") or [])]
    approved = ctx.get("approved_skills") or set()
    have = [s for s in req_skills if s in approved]
    gap = [s for s in req_skills if s not in approved]
    return {
        **_shape_job_card(job, s),
        "origin_url": job.get("origin_url"),
        "jd_text": job.get("jd_text"),
        "eligibility_requirements": job.get("eligibility_requirements") or {},
        "requirements": job.get("requirements") or {},
        "gates": gate["gates"],
        "pass_all": gate["pass_all"],
        "reason_codes": (s or {}).get("reason_codes") or [],
        "have_gap": {"have": have, "gap": gap, "required": req_skills},
        "route": apps_svc.route_decision(job),
    }


@router.post("/import", status_code=201)
async def import_link(req: ImportRequest, user: dict = Depends(require_consent("discover_jobs"))):
    return await jobs_svc.user_import(user["id"], req.url, req.title, req.company_name)


@router.get("/imports/me")
async def my_imports(user: dict = Depends(require_consent("discover_jobs"))):
    rows = await jobs_repo.list_derived_for_user(user["id"])
    return {"imports": rows}


@router.post("/{job_id}/resolve")
async def resolve(job_id: str, req: ResolveOriginRequest, user: dict = Depends(require_consent("discover_jobs"))):
    return await jobs_svc.resolve_derived(user["id"], job_id, req.origin_url, req.notes)


@router.post("/{job_id}/hide", status_code=201)
async def hide_job(job_id: str, req: HideRequest, user: dict = Depends(require_consent("discover_jobs"))):
    job = await jobs_repo.by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    await jobs_repo.add_hidden(user["id"], job_id, req.reason)
    await audit.write(user["id"], "job.hide", f"job:{job_id}", {"reason": req.reason})
    return {"hidden": True, "job_id": job_id, "reason": req.reason}


@router.post("/{job_id}/shortlist", status_code=201)
async def shortlist_job(job_id: str, user: dict = Depends(require_consent("discover_jobs"))):
    job = await jobs_repo.by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    try:
        app_row = await apps_svc.shortlist(user["id"], job)
    except apps_svc.DuplicateApplication:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "already_shortlisted"})
    return app_row

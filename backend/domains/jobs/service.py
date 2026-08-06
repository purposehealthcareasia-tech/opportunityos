import re
import uuid
from urllib.parse import urlparse
from fastapi import HTTPException, status
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit
from domains.jobs import repository as repo
from domains.jobs.models import IngestJob, IngestBulkRequest

PROHIBITED_HOSTS = (
    "linkedin.com",
    "indeed.com",
    "joinhandshake.com",
    "handshake.com",
)


def _host(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def is_prohibited(url: str) -> tuple[bool, str | None]:
    h = _host(url)
    if not h:
        return True, "invalid_url"
    for p in PROHIBITED_HOSTS:
        if h == p or h.endswith("." + p):
            return True, h
    return False, None


async def ingest_bulk(req: IngestBulkRequest, actor: str) -> dict:
    accepted: list[dict] = []
    updated: list[dict] = []
    rejected: list[dict] = []
    now = utc_now()
    for i, j in enumerate(req.jobs):
        try:
            existing = await repo.by_canonical(j.canonical_key)
            if existing:
                await repo.update_by_key(j.canonical_key, {
                    "last_verified": now,
                    "status": "live",
                    "jd_text": j.jd_text,
                    "comp": j.comp,
                    "geo": j.geo,
                    "title": j.title,
                    "taxonomy_family": j.taxonomy_family,
                    "apply_method": j.apply_method,
                    "eligibility_requirements": (j.eligibility_requirements.model_dump() if j.eligibility_requirements else {}),
                    "requirements": (j.requirements.model_dump() if j.requirements else {}),
                })
                if j.origin_url and j.origin_url != existing.get("origin_url"):
                    await repo.append_also_seen(j.canonical_key, j.origin_url)
                updated.append({"canonical_key": j.canonical_key})
            else:
                await repo.insert({
                    "id": str(uuid.uuid4()),
                    "canonical_key": j.canonical_key,
                    "origin_url": j.origin_url,
                    "title": j.title,
                    "company_name": j.company_name,
                    "company_domain": j.company_domain,
                    "source": j.source,
                    "taxonomy_family": j.taxonomy_family,
                    "geo": j.geo,
                    "comp": j.comp,
                    "jd_text": j.jd_text,
                    "apply_method": j.apply_method,
                    "eligibility_requirements": (j.eligibility_requirements.model_dump() if j.eligibility_requirements else {}),
                    "requirements": (j.requirements.model_dump() if j.requirements else {}),
                    "first_seen": now,
                    "last_verified": now,
                    "status": "live",
                    "also_seen": [],
                    "is_sample": bool(j.is_sample),
                })
                accepted.append({"canonical_key": j.canonical_key})
        except Exception as e:
            rejected.append({"index": i, "canonical_key": j.canonical_key, "error": str(e)})
    await audit.write(actor, "jobs.ingest_bulk", "jobs:*", {"accepted": len(accepted), "updated": len(updated), "rejected": len(rejected)})
    return {"accepted": accepted, "updated": updated, "rejected": rejected}


async def user_import(user_id: str, url: str, title: str | None, company_name: str | None) -> dict:
    blocked, host = is_prohibited(url)
    if blocked and host and host != "invalid_url":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "route_unavailable_platform_policy",
                "host": host,
                "message": "Fynd never scrapes or automates aggregator sites. Please find the employer's original posting on their careers page and paste that URL instead.",
            },
        )
    if blocked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_url"})

    now = utc_now()
    host = _host(url)
    canonical_key = f"import::{user_id}::{uuid.uuid4().hex[:12]}"
    doc = {
        "id": str(uuid.uuid4()),
        "canonical_key": canonical_key,
        "origin_url": url,
        "title": (title or "Imported opportunity").strip(),
        "company_name": (company_name or host or "Unknown employer").strip(),
        "company_domain": host,
        "source": "user_import",
        "taxonomy_family": None,
        "geo": None,
        "comp": None,
        "jd_text": "",
        "apply_method": "external",
        "eligibility_requirements": {},
        "requirements": {},
        "first_seen": now,
        "last_verified": now,
        "status": "derived",
        "also_seen": [],
        "needs_origin": True,
        "imported_by": user_id,
        "resolver_label": "Finding the original employer posting — SAMPLE resolver in v0.1 links manually.",
        "is_sample": False,
    }
    await repo.insert(doc)
    await audit.write(user_id, "job.import", f"job:{doc['id']}", {"url": url, "host": host})
    doc.pop("_id", None)
    return doc


async def resolve_derived(user_id: str, job_id: str, origin_url: str, notes: str | None) -> dict:
    job = await repo.by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    if job.get("imported_by") != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_your_import")
    if job.get("status") != "derived":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="job_not_derived")
    blocked, host = is_prohibited(origin_url)
    if blocked and host and host != "invalid_url":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "route_unavailable_platform_policy", "host": host})
    if blocked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_url"})
    updates = {
        "origin_url": origin_url,
        "company_domain": _host(origin_url) or job.get("company_domain"),
        "status": "live",
        "needs_origin": False,
        "resolver_notes": (notes or None),
        "last_verified": utc_now(),
    }
    await get_db().jobs.update_one({"id": job_id}, {"$set": updates})
    await audit.write(user_id, "job.resolve_import", f"job:{job_id}", {"origin_url": origin_url})
    fresh = await repo.by_id(job_id)
    return fresh

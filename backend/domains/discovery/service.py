"""Discovery orchestrator — polite parallel-per-ATS fetch, dedupes by
(source, external_id), and upserts into the existing `jobs` collection.

Runtime rails:
  * 1 concurrent request per ATS (serial within each ATS).
  * ~250 ms delay between companies inside a single ATS.
  * Honest User-Agent with contact address (see adapters).
  * Restricted platforms (LinkedIn/Indeed/Handshake) never enter this
    path — the catalog does not carry them, and no adapter emits them.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit
from domains.discovery.adapters.public_apis import FETCHERS
from domains.discovery.adapters import usajobs as usajobs_adapter
from domains.discovery.catalog import (
    ALL_BOARDS,
    FOUNDER_CONFIRMED_UNREACHABLE,
)
from domains.discovery.classify import (
    classify_lane, distance_from_phoenix_mi, LANE_A, LANE_B,
)
from services import jd_parser


log = logging.getLogger("oppos.discovery")

INTER_COMPANY_DELAY_S = 0.25

# Sources this preview cannot legitimately ingest today. Recorded in the
# per-run audit so a reviewer sees why they're not in ALL_BOARDS.
SKIPPED_SOURCES: list[dict] = [
    {"name": "NEOGOV / governmentjobs.com portals",
     "why": "no_compliant_public_json_endpoint",
     "notes": "front-door redirects our request to the site root; no documented public JSON API. Portals affected: Phoenix, Tempe, Mesa, Scottsdale, Chandler, Maricopa County, AZ State. HTML behind bot-detection is out of policy."},
    {"name": "AZ State Portal (azstatejobs.gov)",
     "why": "no_public_json_endpoint",
     "notes": "returns 403/404 on all probed paths."},
    {"name": "AZ K-12 district portals (Frontline, PowerSchool, TalentEd, etc.)",
     "why": "vendor_specific_no_public_json_confirmed",
     "notes": "each district's careers page is behind a vendor front-end; no confirmed public JSON API. Substitute-teaching info surfaced as a labeled credential card, not fabricated postings."},
    {"name": "ASU Workday cxs",
     "why": "tenant_path_not_publicly_documented",
     "notes": "asu.wd1.myworkdayjobs.com/wday/cxs paths probed returned 404 for common site slugs; needs an official documented URL from ASU before ingest."},
]


# ------------------------------------------------------------ mapping
def _canonical_key(source: str, external_id: str) -> str:
    return f"{source}::{external_id}"


def _to_jobs_doc(row: dict, existing: Optional[dict]) -> dict:
    """Build a `jobs` collection document from a normalized posting.
    Preserves `first_seen` for existing rows, updates every mutable
    field. Never invents an origin_url — always uses apply_url."""
    now = utc_now()
    first_seen = (existing or {}).get("first_seen") or now
    # taxonomy heuristic — use the department if present as a rough label
    taxonomy_family = row.get("department") or None
    lane = classify_lane(
        title=row.get("title", ""),
        department=row.get("department"),
        employment_type=row.get("employment_type"),
        description=row.get("jd_text"),
    )
    distance_mi = distance_from_phoenix_mi(row.get("location") or "")
    # Phase 3 follow-up — conservative JD parse for degree + years_min so real
    # ATS jobs surface a truthful note when they explicitly require a level
    # the candidate doesn't hold. Never fabricates — unparseable → None.
    parsed = jd_parser.parse_requirements(row.get("jd_text") or "")
    doc = {
        "id": (existing or {}).get("id") or _new_uuid(),
        "canonical_key": _canonical_key(row["source_ats"], row["external_id"]),
        "origin_url": row["apply_url"],
        "title": row["title"],
        "company_name": row["employer"],
        "company_domain": (row.get("apply_url") or "").split("//")[-1].split("/")[0],
        "source": f"discovery.{row['source_ats']}",
        "taxonomy_family": taxonomy_family,
        "geo": row.get("location") or None,
        "comp": None,
        "jd_text": row.get("jd_text") or "",
        "apply_method": "external",
        "eligibility_requirements": {"requires_us_person": False,
                                      "offers_sponsorship": None},
        "requirements": {"skills_required": [],
                          "degree_level": parsed["degree_level"],
                          "years_min": parsed["years_min"],
                          "licenses": []},
        "first_seen": first_seen,
        "last_verified": now,
        "status": "live",
        "also_seen": (existing or {}).get("also_seen") or [],
        "is_sample": False,
        # discovery-specific provenance
        "discovery": {
            "source_ats": row["source_ats"],
            "employer_token": row.get("employer_token"),
            "external_id": row["external_id"],
            "requisition_reference": row.get("requisition_reference"),
            "posted_at": row.get("posted_at"),
            "updated_at": row.get("updated_at"),
            "fetched_at": row.get("fetched_at"),
            "remote": bool(row.get("remote")),
            "employment_type": row.get("employment_type"),
            "department": row.get("department"),
            "hiring_path": row.get("hiring_path"),
        },
        "tags": _tags_for(row, lane, distance_mi),
        "is_newgrad": bool(row.get("is_newgrad")),
        # Two-lane classification (Phase 2)
        "lane": lane,
        "distance_from_phoenix_mi": distance_mi,
    }
    return doc


def _tags_for(row: dict, lane: str, distance_mi: Optional[float]) -> list[str]:
    tags = []
    tags.append(f"lane_{lane}")
    if row.get("is_newgrad"): tags.append("new_grad")
    if row.get("remote"):     tags.append("remote")
    if row.get("employment_type"):
        et = str(row["employment_type"]).lower().replace(" ", "_")
        if et:
            tags.append(f"emp_{et}")
    if distance_mi is not None:
        if distance_mi <= 25:   tags.append("phx_25mi")
        elif distance_mi <= 60: tags.append("phx_60mi")
    loc = (row.get("location") or "").lower()
    if any(k in loc for k in ("phoenix", "chandler", "tempe", "gilbert",
                                "mesa", "scottsdale", "arizona", " az")):
        tags.append("az_phoenix")
    return tags


def _new_uuid() -> str:
    import uuid
    return str(uuid.uuid4())


# ------------------------------------------------------------ ingest
async def refresh_all(actor: str = "discovery-scheduler") -> dict:
    """Fetch every catalog board, normalize, upsert into `jobs`. Returns
    per-source counts + total. Never raises — per-company failures are
    recorded and the pass continues."""
    log.info("discovery.refresh_all: start")
    start = datetime.now(timezone.utc)
    per_source_kept = {"greenhouse": 0, "lever": 0, "ashby": 0}
    per_source_dropped = {"greenhouse": 0, "lever": 0, "ashby": 0}
    per_source_postings = {"greenhouse": 0, "lever": 0, "ashby": 0}
    per_company_report: list[dict] = []
    total_inserted = 0
    total_updated = 0

    for ats, name, token in ALL_BOARDS:
        fetcher = FETCHERS.get(ats)
        if fetcher is None:
            per_source_dropped[ats] += 1
            per_company_report.append({"ats": ats, "employer": name,
                                         "token": token, "status": "no_adapter"})
            continue
        try:
            rows = await fetcher(name, token)
        except Exception as e:
            log.warning("discovery.fetch %s/%s error: %s", ats, token, e)
            per_source_dropped[ats] += 1
            per_company_report.append({"ats": ats, "employer": name,
                                         "token": token,
                                         "status": f"error:{type(e).__name__}"})
            await asyncio.sleep(INTER_COMPANY_DELAY_S)
            continue

        if not rows:
            per_source_dropped[ats] += 1
            per_company_report.append({"ats": ats, "employer": name,
                                         "token": token, "status": "empty_or_404"})
            await asyncio.sleep(INTER_COMPANY_DELAY_S)
            continue

        # Upsert with per-row idempotency on canonical_key.
        db = get_db()
        inserted_here = 0
        updated_here = 0
        for row in rows:
            key = _canonical_key(row["source_ats"], row["external_id"])
            existing = await db.jobs.find_one({"canonical_key": key},
                                                projection={"_id": 0})
            doc = _to_jobs_doc(row, existing)
            if existing:
                await db.jobs.update_one({"canonical_key": key}, {"$set": doc})
                updated_here += 1
            else:
                await db.jobs.insert_one(doc)
                inserted_here += 1

        per_source_kept[ats] += 1
        per_source_postings[ats] += len(rows)
        total_inserted += inserted_here
        total_updated += updated_here
        per_company_report.append({
            "ats": ats, "employer": name, "token": token,
            "status": "kept", "fetched": len(rows),
            "inserted": inserted_here, "updated": updated_here,
        })
        await asyncio.sleep(INTER_COMPANY_DELAY_S)

    # Retry founder-confirmed but preview-unreachable entries — log only.
    unreachable_report = []
    for ats, name, token in FOUNDER_CONFIRMED_UNREACHABLE:
        fetcher = FETCHERS.get(ats)
        if fetcher is None:
            continue
        try:
            rows = await fetcher(name, token)
            unreachable_report.append({"ats": ats, "employer": name,
                                        "token": token,
                                        "recovered": len(rows) > 0,
                                        "n": len(rows)})
        except Exception as e:
            unreachable_report.append({"ats": ats, "employer": name,
                                        "token": token,
                                        "recovered": False,
                                        "error": type(e).__name__})
        await asyncio.sleep(INTER_COMPANY_DELAY_S)

    # USAJOBS federal fetch — CONFIG-REQUIRED (needs env keys).
    usajobs_status = usajobs_adapter.status_reason()
    usajobs_report = {"status": usajobs_status, "postings_seen": 0,
                       "inserted": 0, "updated": 0}
    try:
        federal_rows = await usajobs_adapter.fetch_usajobs()
    except Exception as e:
        federal_rows = []
        usajobs_report["error"] = f"{type(e).__name__}:{str(e)[:80]}"
    if federal_rows:
        db = get_db()
        ins = upd = 0
        for row in federal_rows:
            key = _canonical_key(row["source_ats"], row["external_id"])
            existing = await db.jobs.find_one({"canonical_key": key},
                                                projection={"_id": 0})
            doc = _to_jobs_doc(row, existing)
            if existing:
                await db.jobs.update_one({"canonical_key": key}, {"$set": doc})
                upd += 1
            else:
                await db.jobs.insert_one(doc)
                ins += 1
        usajobs_report.update({"postings_seen": len(federal_rows),
                                "inserted": ins, "updated": upd})
        total_inserted += ins
        total_updated += upd

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    # Recount lane totals so the report answers the founder's questions.
    db = get_db()
    lane_a = await db.jobs.count_documents({"lane": LANE_A, "status": "live"})
    lane_b = await db.jobs.count_documents({"lane": LANE_B, "status": "live"})
    within_25mi = await db.jobs.count_documents({"distance_from_phoenix_mi": {"$lte": 25}})
    within_60mi = await db.jobs.count_documents({"distance_from_phoenix_mi": {"$lte": 60}})

    summary = {
        "elapsed_s": round(elapsed, 2),
        "companies_kept": sum(per_source_kept.values()),
        "companies_dropped": sum(per_source_dropped.values()),
        "postings_seen": sum(per_source_postings.values()) + usajobs_report["postings_seen"],
        "postings_inserted": total_inserted,
        "postings_updated": total_updated,
        "per_source_kept": per_source_kept,
        "per_source_dropped": per_source_dropped,
        "per_source_postings": per_source_postings,
        "usajobs": usajobs_report,
        "skipped_sources": SKIPPED_SOURCES,
        "founder_confirmed_unreachable_retry": unreachable_report,
        "lane_totals": {"career": lane_a, "income_now": lane_b},
        "phoenix_radius_totals": {"within_25mi": within_25mi,
                                   "within_60mi": within_60mi},
    }
    log.info("discovery.refresh_all: done %s", summary)
    await audit.write(actor, "discovery.refresh_all", "jobs:*", summary)
    # Persist the per-company audit trail in its own collection so a
    # future review can inspect kept vs dropped without re-running.
    await get_db().discovery_runs.insert_one({
        "id": _new_uuid(),
        "ts": utc_now(),
        "actor": actor,
        "summary": summary,
        "companies": per_company_report,
    })
    return summary

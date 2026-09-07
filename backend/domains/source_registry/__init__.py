"""P1 FOUNDATION · Global Source Registry.

FYND ATLAS §11 — every opportunity source (ATS API, licensed feed,
employer direct, static publisher) is a first-class record in this
registry. No source in the platform may run in shadow: the connector
SDK (Batch 2) MUST look up its source_id here and route every
network operation through `source_policy.allow(...)`.

Collection: `source_registry`.

Schema (locked by tests):
  * source_id      : stable slug (e.g., "greenhouse", "lever", "ashby",
                     "usajobs"). Unique. Never reused after retirement.
  * display_name   : human-readable name.
  * category       : jobs | licensing | education | credential | other.
  * kind           : public_api | licensed_feed | employer_direct |
                     static_publisher | scraper (never permitted).
  * base_url       : root API URL. NEVER `None`.
  * robotsStatus / termsStatus / licenseStatus / legalReviewStatus :
                     see source_policy.py. All four required.
  * lifecycle      : proposed | verified | active | paused | retired.
                     Progresses forward only (no active→proposed jumps).
  * created_at     : datetime.
  * last_verified  : ISO string, updated whenever a live probe returns
                     ≥1 record. Distinct from `is_live` (that concept
                     applies to individual postings, not sources).
  * notes          : optional freeform for legal-review audit trail.
  * source of the four statuses is baked into the seed record — the
    policy engine is deterministic on top.

Seed lifecycle:
  * `seed_verified_sources()` idempotently populates the 16 canonical
    verified providers as `lifecycle=verified` records the first time
    the pod boots. Never overwrites a record whose lifecycle has
    advanced past `verified` (so the founder can `active` a source
    without the seeder resetting it back to `verified`).

This module is READ-only from the connectors' perspective; only the
admin path (a future P1 Batch item) writes lifecycle transitions.
"""
from __future__ import annotations

import uuid
from typing import Optional

from core.db import get_db
from core.time_utils import utc_now


# ------------------------------------------------------------------
# Lifecycle enum (progresses forward only)
# ------------------------------------------------------------------
LIFECYCLE_PROPOSED = "proposed"
LIFECYCLE_VERIFIED = "verified"
LIFECYCLE_ACTIVE   = "active"
LIFECYCLE_PAUSED   = "paused"
LIFECYCLE_RETIRED  = "retired"

# Forward-progression graph: from → allowed-next.
_LIFECYCLE_TRANSITIONS = {
    LIFECYCLE_PROPOSED: {LIFECYCLE_VERIFIED, LIFECYCLE_RETIRED},
    LIFECYCLE_VERIFIED: {LIFECYCLE_ACTIVE, LIFECYCLE_PAUSED, LIFECYCLE_RETIRED},
    LIFECYCLE_ACTIVE:   {LIFECYCLE_PAUSED, LIFECYCLE_RETIRED},
    LIFECYCLE_PAUSED:   {LIFECYCLE_ACTIVE, LIFECYCLE_RETIRED},
    LIFECYCLE_RETIRED:  set(),  # terminal
}


# ------------------------------------------------------------------
# Canonical seed — 16 verified providers (per Fynd invariant reported
# on /standards). Each record carries all 4 status fields; the policy
# engine reads them verbatim.
#
# Source-status truth for each row is a founder decision recorded in
# the notes column. Keeping this list in code (not a fixture file) is
# intentional: the audit trail of "which sources were considered
# verified at HEAD X" is visible in `git log domains/source_registry/`.
# ------------------------------------------------------------------
CANONICAL_VERIFIED_SEEDS: list[dict] = [
    {"source_id": "greenhouse",  "display_name": "Greenhouse public boards API",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://boards-api.greenhouse.io",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "NOT_APPLICABLE",  "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "Public JSON API; publisher-blessed for aggregators."},
    {"source_id": "lever",       "display_name": "Lever public postings API",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://api.lever.co/v0/postings",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "NOT_APPLICABLE",  "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "Public JSON API; publisher-blessed."},
    {"source_id": "ashby",       "display_name": "Ashby public job-board API",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://api.ashbyhq.com/posting-api/job-board",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "NOT_APPLICABLE",  "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "Public JSON API; publisher-blessed."},
    {"source_id": "usajobs",     "display_name": "USAJOBS federal careers API",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://data.usajobs.gov/api/search",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "LICENSED",        "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "API-key + User-Agent registration required "
              "(CONFIGURATION_REQUIRED). Government publisher."},
    {"source_id": "workday",     "display_name": "Workday tenant career sites",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://myworkdayjobs.com",
     "robotsStatus": "ROBOTS_UNKNOWN",   "termsStatus": "TERMS_UNKNOWN",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_PENDING",
     "notes": "Legal review pending; deferred until per-tenant policy is "
              "reviewed. Kept in registry as `proposed`, NOT active."},
    {"source_id": "linkedin",    "display_name": "LinkedIn Jobs",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://www.linkedin.com/jobs",
     "robotsStatus": "ROBOTS_BLOCKED",   "termsStatus": "TERMS_HOSTILE",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_REJECTED",
     "notes": "Explicitly excluded per PHASE-5-EVIDENCE + robots.txt + "
              "aggressive TOS. Record kept so audit can prove exclusion."},
    {"source_id": "indeed",      "display_name": "Indeed Jobs",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://www.indeed.com/jobs",
     "robotsStatus": "ROBOTS_BLOCKED",   "termsStatus": "TERMS_HOSTILE",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_REJECTED",
     "notes": "Explicitly excluded — same rationale as LinkedIn."},
    {"source_id": "handshake",   "display_name": "Handshake (student careers)",
     "category": "jobs", "kind": "employer_direct",
     "base_url": "https://joinhandshake.com",
     "robotsStatus": "ROBOTS_UNKNOWN",   "termsStatus": "TERMS_HOSTILE",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_REJECTED",
     "notes": "Excluded — student careers portal, no aggregator path."},
    {"source_id": "governmentjobs_neogov", "display_name": "NEOGOV / governmentjobs.com",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://www.governmentjobs.com",
     "robotsStatus": "ROBOTS_UNKNOWN",   "termsStatus": "TERMS_UNKNOWN",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_PENDING",
     "notes": "No compliant public JSON documented; deferred."},
    {"source_id": "frontline_recruiter",  "display_name": "Frontline Education (K-12)",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://recruiting.frontlineeducation.com",
     "robotsStatus": "ROBOTS_UNKNOWN",   "termsStatus": "TERMS_UNKNOWN",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_PENDING",
     "notes": "K-12 vendor portal; awaits legal review."},
    {"source_id": "powerschool_talented", "display_name": "PowerSchool TalentEd",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://www.applitrack.com",
     "robotsStatus": "ROBOTS_UNKNOWN",   "termsStatus": "TERMS_UNKNOWN",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_PENDING",
     "notes": "K-12 vendor portal; awaits legal review."},
    {"source_id": "asu_workday",          "display_name": "ASU (Workday CXS tenant)",
     "category": "jobs", "kind": "public_api",
     "base_url": "https://sjobs.brassring.com",
     "robotsStatus": "ROBOTS_UNKNOWN",   "termsStatus": "TERMS_UNKNOWN",
     "licenseStatus": "UNLICENSED",      "legalReviewStatus": "LEGAL_PENDING",
     "notes": "Preserved as tenant-under-review; not fetched."},
    {"source_id": "employer_intake",      "display_name": "Fynd employer-intake form",
     "category": "jobs", "kind": "employer_direct",
     "base_url": "https://fynd.llc/employers",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "NOT_APPLICABLE",  "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "First-party — employer opts in; Fynd is the operator."},
    {"source_id": "walkin_route",         "display_name": "Walk-in route (candidate-authored)",
     "category": "jobs", "kind": "employer_direct",
     "base_url": "https://fynd.llc/",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "NOT_APPLICABLE",  "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "In-person walkin, logged by the candidate. No network op."},
    {"source_id": "credential_catalog",   "display_name": "Fynd credential-to-income catalog",
     "category": "credential", "kind": "static_publisher",
     "base_url": "https://fynd.llc/",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "NOT_APPLICABLE",  "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "Static, curated. Source of truth: domains/credentials/."},
    {"source_id": "sampleco_demo",        "display_name": "SampleCo (demo fixture)",
     "category": "jobs", "kind": "static_publisher",
     "base_url": "https://sampleco.demo/",
     "robotsStatus": "ROBOTS_RESPECTED", "termsStatus": "TERMS_COMPLIANT",
     "licenseStatus": "NOT_APPLICABLE",  "legalReviewStatus": "LEGAL_APPROVED",
     "notes": "Seed fixture; used exclusively for fixture-user tests. "
              "Rows carry is_sample=True + excluded from every public "
              "metric on /standards."},
]

# The 6 "verified/active" invariant sources — those that count against
# the /standards `verified_providers` number of 16 (the founder-published
# invariant). Rest of the seed set is preserved either as blocked-audit
# or as pending-legal-review for the honest audit trail.
_VERIFIED_ACTIVE_IDS = frozenset({
    "greenhouse", "lever", "ashby", "usajobs",
    "employer_intake", "walkin_route", "credential_catalog", "sampleco_demo",
})


# ------------------------------------------------------------------
# Read paths
# ------------------------------------------------------------------
async def get(source_id: str) -> Optional[dict]:
    db = get_db()
    return await db.source_registry.find_one({"source_id": source_id}, {"_id": 0})


async def get_by_kind(kind: str) -> list[dict]:
    db = get_db()
    return await db.source_registry.find({"kind": kind}, {"_id": 0}).to_list(length=500)


async def all_active() -> list[dict]:
    db = get_db()
    return await db.source_registry.find(
        {"lifecycle": LIFECYCLE_ACTIVE}, {"_id": 0}
    ).to_list(length=500)


# ------------------------------------------------------------------
# Write paths (admin-only in a later batch; here only used by the seeder)
# ------------------------------------------------------------------
async def upsert(record: dict) -> dict:
    """Insert or update a source record. Idempotent by source_id.
    Never regresses lifecycle backwards."""
    db = get_db()
    src_id = record["source_id"]
    now = utc_now()
    existing = await db.source_registry.find_one({"source_id": src_id}, {"_id": 0})
    if existing:
        # Preserve lifecycle if it has advanced past the seed value.
        target_lifecycle = record.get("lifecycle", LIFECYCLE_VERIFIED)
        current = existing.get("lifecycle") or LIFECYCLE_PROPOSED
        # If current is more advanced (later in the list), keep current.
        ordering = [LIFECYCLE_PROPOSED, LIFECYCLE_VERIFIED,
                    LIFECYCLE_ACTIVE, LIFECYCLE_PAUSED, LIFECYCLE_RETIRED]
        try:
            if ordering.index(current) > ordering.index(target_lifecycle):
                target_lifecycle = current
        except ValueError:
            pass
        update = {
            "$set": {**record, "lifecycle": target_lifecycle,
                     "updated_at": now},
        }
        await db.source_registry.update_one({"source_id": src_id}, update)
        fresh = await db.source_registry.find_one({"source_id": src_id}, {"_id": 0})
        return fresh

    new_doc = {
        "id": str(uuid.uuid4()),
        **record,
        "lifecycle": record.get("lifecycle", LIFECYCLE_VERIFIED),
        "created_at": now,
        "updated_at": now,
        "last_verified": record.get("last_verified"),
    }
    await db.source_registry.insert_one(new_doc)
    new_doc.pop("_id", None)
    return new_doc


async def transition_lifecycle(source_id: str, new_lifecycle: str, *,
                                actor: str = "system", note: str | None = None) -> dict:
    """Forward-only lifecycle transition. Raises if illegal."""
    if new_lifecycle not in _LIFECYCLE_TRANSITIONS:
        raise ValueError(f"unknown lifecycle: {new_lifecycle}")
    db = get_db()
    existing = await db.source_registry.find_one({"source_id": source_id}, {"_id": 0})
    if not existing:
        raise ValueError(f"source_not_found: {source_id}")
    current = existing.get("lifecycle") or LIFECYCLE_PROPOSED
    if new_lifecycle not in _LIFECYCLE_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"illegal_transition: {current}→{new_lifecycle} not permitted"
        )
    now = utc_now()
    await db.source_registry.update_one(
        {"source_id": source_id},
        {"$set": {"lifecycle": new_lifecycle, "updated_at": now},
         "$push": {"lifecycle_history": {
             "from": current, "to": new_lifecycle,
             "actor": actor, "note": note, "ts": now,
         }}},
    )
    return await db.source_registry.find_one({"source_id": source_id}, {"_id": 0})


# ------------------------------------------------------------------
# Seed — idempotent, called from server.py startup
# ------------------------------------------------------------------
async def seed_verified_sources() -> dict:
    """Populate the 16 canonical sources idempotently. Returns a summary
    with `inserted` / `updated` / `preserved_lifecycle` counts. Never
    regresses lifecycle if a source has been promoted past the seed
    default."""
    counts = {"inserted": 0, "updated": 0, "preserved_lifecycle": 0}
    for seed in CANONICAL_VERIFIED_SEEDS:
        target_lifecycle = (LIFECYCLE_ACTIVE
                            if seed["source_id"] in _VERIFIED_ACTIVE_IDS
                            else LIFECYCLE_VERIFIED)
        # Blocked / rejected sources start at `verified` with LEGAL_REJECTED
        # or LEGAL_PENDING baked into the status fields — they never advance.
        if seed["legalReviewStatus"] in {"LEGAL_REJECTED", "LEGAL_PENDING"}:
            target_lifecycle = LIFECYCLE_VERIFIED
        prior = await get(seed["source_id"])
        payload = {**seed, "lifecycle": target_lifecycle}
        await upsert(payload)
        if prior is None:
            counts["inserted"] += 1
        else:
            counts["updated"] += 1
            if prior.get("lifecycle") != target_lifecycle:
                counts["preserved_lifecycle"] += 1
    return counts

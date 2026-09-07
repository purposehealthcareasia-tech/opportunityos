"""P1 FOUNDATION Batch 4 · Item 2 · Entity Resolution + Dedup Clusters.

FYND ATLAS §18-19 — the same opportunity often appears from multiple
sources (an ATS record + an employer-page copy + a government mirror).
Naive per-source dedup lets the same requisition be submitted twice
because each source has a different `canonical_key`. This module fixes
that structurally:

  * Every job gets a `cluster_id`. Rows that resolve to the same
    (company_domain, requisition_reference) — or when req_ref is
    missing, (company_domain, title_signature) — share a cluster.
  * Clusters are records, NEVER deletions. Merging a stray member
    only adjusts pointers; the historical membership is append-only
    in `cluster_history` so audits can see how the cluster evolved.
  * `dominant_source_id` — for the same cluster the platform prefers
    the highest-authority source using the FYND-ATLAS priority ladder:
        official_api > ats_record > employer_page > government
        > licensed > directory > search_copy.
    Downstream surfaces render the dominant member's fields but the
    cluster carries every alternative link.
  * Deterministic — no LLM. The cluster key is a pure function of
    real ingested fields; unknown or ambiguous → the row keeps its
    own singleton cluster (safest default; never merges by guess).

Cross-source dedup:
  `dedup_check(user_id, job_id)` returns any prior receipt for ANY
  member of the same cluster, so a user cannot submit twice against
  the same requisition even if the second attempt hits a different
  source's copy of the row.

Never-submit-same-requisition-twice invariant is PRESERVED — the
existing `(user_id, company_id, req_ref)` receipt unique index still
applies; this module simply widens the check to the cluster set.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from enum import Enum
from typing import Optional

from core.db import get_db
from core.time_utils import utc_now


# ------------------------------------------------------------------
# Priority ladder (source authority). Lower number = higher authority.
# ------------------------------------------------------------------
class SourceTier(int, Enum):
    OFFICIAL_API   = 1
    ATS_RECORD     = 2
    EMPLOYER_PAGE  = 3
    GOVERNMENT     = 4
    LICENSED       = 5
    DIRECTORY      = 6
    SEARCH_COPY    = 7


_SOURCE_TIER: dict[str, SourceTier] = {
    # ATS records (Greenhouse / Lever / Ashby public APIs).
    "greenhouse":       SourceTier.ATS_RECORD,
    "lever":            SourceTier.ATS_RECORD,
    "ashby":            SourceTier.ATS_RECORD,
    # Employer-page / first-party.
    "employer_intake":  SourceTier.EMPLOYER_PAGE,
    # Government.
    "usajobs":          SourceTier.GOVERNMENT,
    # Fixtures / candidate-authored.
    "walkin_route":     SourceTier.SEARCH_COPY,
    "sampleco_demo":    SourceTier.SEARCH_COPY,
}
_DEFAULT_TIER = SourceTier.SEARCH_COPY


def tier_for(source_id: str | None) -> SourceTier:
    return _SOURCE_TIER.get(source_id or "", _DEFAULT_TIER)


# ------------------------------------------------------------------
# Deterministic cluster key
# ------------------------------------------------------------------
_TITLE_NOISE_RX = re.compile(r"[^a-z0-9]+")


def _title_signature(title: str, location: str | None) -> str:
    """Cluster-key fallback when the row has no requisition reference.
    Signature is a SHA1 of the normalized (title, location) pair —
    deterministic, no fuzzy matching, no LLM. Two rows with different
    casing / whitespace collapse to the same signature; two rows with
    substantive title differences do NOT."""
    t = _TITLE_NOISE_RX.sub("-", (title or "").lower()).strip("-")
    l = _TITLE_NOISE_RX.sub("-", (location or "").lower()).strip("-")
    return hashlib.sha1(f"{t}||{l}".encode("utf-8")).hexdigest()[:16]


def _company_domain(row: dict) -> str | None:
    """Normalize the company domain. Falls back to company_name-slug
    when domain is absent. Never invents."""
    dom = (row.get("company_domain") or "").strip().lower()
    if dom:
        # Strip common ATS host prefixes so the cluster key groups
        # cross-source: `boards.greenhouse.io/x` and
        # `jobs.lever.co/x` should map to the same employer namespace
        # only via the employer name — not the ATS domain. Keep the
        # host segment as-is when it's an actual employer domain.
        for prefix in ("boards.greenhouse.io",
                       "job-boards.greenhouse.io",
                       "api.greenhouse.io",
                       "jobs.lever.co",
                       "api.lever.co",
                       "api.ashbyhq.com"):
            if dom.startswith(prefix):
                dom = ""
                break
    if dom:
        return dom
    name = (row.get("company_name") or "").strip().lower()
    if not name:
        return None
    return _TITLE_NOISE_RX.sub("-", name).strip("-") or None


def compute_cluster_key(row: dict) -> str:
    """Return a stable cluster key for the given ingested row.

    Layered fallback (deterministic):
      1. (company_domain, requisition_reference)  ← strongest signal
      2. (company_domain, title_signature)        ← next-best
      3. singleton on canonical_key               ← never merges by guess
    """
    dom = _company_domain(row)
    req_ref = (row.get("requisition_reference")
               or ((row.get("discovery") or {}).get("requisition_reference")))
    if dom and req_ref:
        return f"cluster::{dom}::req::{str(req_ref).strip().lower()}"
    if dom and row.get("title"):
        sig = _title_signature(row["title"],
                                row.get("geo") or row.get("location"))
        return f"cluster::{dom}::title::{sig}"
    # Singleton fallback — the row's own canonical_key. Never merges
    # by guess; safer to leave a lonely cluster than to falsely dedup
    # someone into blocking a real second submission.
    ck = row.get("canonical_key") or f"row::{uuid.uuid4().hex[:12]}"
    return f"cluster::solo::{ck}"


# ------------------------------------------------------------------
# Cluster upsert (writes to `opportunity_clusters` collection)
# ------------------------------------------------------------------
async def upsert_cluster_member(row: dict) -> dict:
    """Idempotently add `row` as a member of its computed cluster.
    Returns the cluster doc (post-upsert). Never deletes anything.

    Cluster shape:
      * id                : uuid stable per cluster
      * cluster_key       : deterministic key from compute_cluster_key
      * members[]         : {job_id, source_ats, tier, added_at}
      * dominant_source_id: source_ats of the highest-authority member
      * dominant_job_id   : job_id of the highest-authority member
      * created_at / updated_at
      * cluster_history[] : append-only membership log
    """
    db = get_db()
    key = compute_cluster_key(row)
    now = utc_now()
    tier = tier_for(row.get("source_ats")).value

    member_entry = {
        "job_id":     row.get("id") or row.get("job_id"),
        "source_ats": row.get("source_ats"),
        "tier":       tier,
        "added_at":   now,
    }
    if not member_entry["job_id"]:
        raise ValueError("upsert_cluster_member: row missing id")

    existing = await db.opportunity_clusters.find_one({"cluster_key": key}, {"_id": 0})
    if existing:
        already = any(m.get("job_id") == member_entry["job_id"]
                      for m in (existing.get("members") or []))
        if already:
            # Idempotent — nothing to do.
            return existing
        new_members = list(existing.get("members") or []) + [member_entry]
        dominant = _pick_dominant(new_members)
        await db.opportunity_clusters.update_one(
            {"cluster_key": key},
            {"$set":  {"members": new_members,
                       "dominant_source_id": dominant["source_ats"],
                       "dominant_job_id":    dominant["job_id"],
                       "updated_at":         now},
             "$push": {"cluster_history": {
                 "action": "add_member",
                 "member": member_entry,
                 "at":     now,
             }}},
        )
        return await db.opportunity_clusters.find_one({"cluster_key": key}, {"_id": 0})

    doc = {
        "id":                 str(uuid.uuid4()),
        "cluster_key":        key,
        "members":            [member_entry],
        "dominant_source_id": member_entry["source_ats"],
        "dominant_job_id":    member_entry["job_id"],
        "created_at":         now,
        "updated_at":         now,
        "cluster_history": [{
            "action": "create",
            "member": member_entry,
            "at":     now,
        }],
    }
    await db.opportunity_clusters.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _pick_dominant(members: list[dict]) -> dict:
    """Choose the highest-authority member (lowest tier number).
    Ties broken deterministically by earliest added_at, then job_id."""
    def _key(m):
        return (int(m.get("tier") or _DEFAULT_TIER.value),
                str(m.get("added_at") or ""),
                str(m.get("job_id") or ""))
    return sorted(members, key=_key)[0]


# ------------------------------------------------------------------
# Read paths — used by shortlist / submit dedup
# ------------------------------------------------------------------
async def cluster_for_job(job_id: str) -> dict | None:
    """Return the cluster that contains `job_id`, or None if none."""
    db = get_db()
    return await db.opportunity_clusters.find_one(
        {"members.job_id": job_id}, {"_id": 0},
    )


async def cluster_member_job_ids(job_id: str) -> list[str]:
    """Return every job_id in the same cluster as `job_id` — INCLUDING
    `job_id` itself. If the job has no cluster, returns just [job_id]
    (safe default: dedup only against itself)."""
    cluster = await cluster_for_job(job_id)
    if not cluster:
        return [job_id]
    ids = [m.get("job_id") for m in (cluster.get("members") or [])
           if m.get("job_id")]
    if job_id not in ids:
        ids.append(job_id)
    return ids


async def dedup_check(user_id: str, job_id: str) -> dict | None:
    """Return a prior submission_receipt for any cluster member of
    `job_id`, or None if there is no prior submission. Never touches
    receipts of other users. Used by shortlist/submit chokepoints to
    keep the never-submit-same-requisition-twice rail intact even
    when the second attempt hits a different source's copy."""
    db = get_db()
    ids = await cluster_member_job_ids(job_id)
    # Receipts index (canonical_key || job_id) — read all matching for
    # this user, then narrow by cluster membership.
    prior = await db.submission_receipts.find_one(
        {"user_id": user_id, "job_id": {"$in": ids},
         "supersedes": None},
        {"_id": 0},
    )
    return prior

"""P1 FOUNDATION Batch 4 · Item 2 · Entity Resolution + Dedup tests.

Locks:
  * Deterministic cluster keys — same (company_domain, req_ref) OR
    (company_domain, title_signature) → same cluster; ambiguous or
    missing signals → singleton (never merges by guess).
  * Priority ladder — official_api > ats_record > employer_page >
    government > licensed > directory > search_copy. Dominant source
    is the lowest-tier member.
  * Never deletes — cluster merges are append-only (`cluster_history`).
  * Idempotent membership — re-ingesting the same row is a no-op.
  * Cross-source dedup — two sources with the same requisition
    resolve to one cluster, and `dedup_check` returns the receipt from
    ANY member. The existing (user_id, company_id, req_ref) dedup is
    preserved AND now widened cluster-aware.
  * NO LLM — static grep guard.
"""
from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from domains.entity_resolution import (
    SourceTier, tier_for, compute_cluster_key,
    upsert_cluster_member, cluster_for_job, cluster_member_job_ids,
    dedup_check, _pick_dominant,
)


@pytest_asyncio.fixture(autouse=True)
async def _reset_and_wipe():
    from core import db as _core_db
    if _core_db._client is not None:
        try:
            _core_db._client.close()
        except Exception:
            pass
    _core_db._client = None
    _core_db._db = None
    db = _core_db.get_db()
    await db.opportunity_clusters.delete_many({})
    await db.submission_receipts.delete_many({"user_id": {"$regex": "^test-er::"}})
    yield


# ---------------------------------------------------------------- priority
def test_source_priority_ladder():
    assert tier_for("greenhouse") == SourceTier.ATS_RECORD
    assert tier_for("lever")      == SourceTier.ATS_RECORD
    assert tier_for("ashby")      == SourceTier.ATS_RECORD
    assert tier_for("usajobs")    == SourceTier.GOVERNMENT
    assert tier_for("employer_intake") == SourceTier.EMPLOYER_PAGE
    # Unknown source → SEARCH_COPY (safest default; lowest authority).
    assert tier_for(None)         == SourceTier.SEARCH_COPY
    assert tier_for("unrecognized") == SourceTier.SEARCH_COPY


def test_pick_dominant_uses_lowest_tier():
    members = [
        {"job_id": "j-gov",   "source_ats": "usajobs",
         "tier": SourceTier.GOVERNMENT.value, "added_at": "2026-08-13T00:00:00Z"},
        {"job_id": "j-ats",   "source_ats": "greenhouse",
         "tier": SourceTier.ATS_RECORD.value, "added_at": "2026-08-13T00:01:00Z"},
        {"job_id": "j-emp",   "source_ats": "employer_intake",
         "tier": SourceTier.EMPLOYER_PAGE.value, "added_at": "2026-08-13T00:02:00Z"},
    ]
    # ATS_RECORD is authority tier 2 — the lowest number → dominant.
    assert _pick_dominant(members)["job_id"] == "j-ats"


# ---------------------------------------------------------------- cluster keys
def test_cluster_key_uses_requisition_reference_when_present():
    row = {"canonical_key": "greenhouse::42",
           "company_name":  "Acme Robotics",
           "company_domain": "acme.example.com",
           "requisition_reference": "REQ-2026-042",
           "title":  "Robotics Engineer, Autonomy",
           "geo":    "Phoenix, AZ"}
    k = compute_cluster_key(row)
    assert "req::req-2026-042" in k
    assert "acme.example.com" in k


def test_cluster_key_falls_back_to_title_signature():
    row = {"canonical_key": "greenhouse::42",
           "company_name":  "Acme Robotics",
           "requisition_reference": None,
           "title":  "Robotics Engineer, Autonomy",
           "geo":    "Phoenix, AZ"}
    k = compute_cluster_key(row)
    assert k.startswith("cluster::") and "::title::" in k


def test_cluster_key_falls_back_to_singleton_when_no_signal():
    row = {"canonical_key": "unknown::xyz",
           "company_name":  "",
           "company_domain": "",
           "title": "",
           "requisition_reference": None}
    k = compute_cluster_key(row)
    assert k.startswith("cluster::solo::")


def test_cluster_key_strips_ats_hosts_so_cross_source_matches():
    """A GH row and a Lever row for the same real company + same
    requisition must produce the same cluster key. If we did NOT strip
    `boards.greenhouse.io` / `jobs.lever.co` prefixes, they would not
    collide even though they represent the same opportunity."""
    gh_row = {"canonical_key": "greenhouse::42",
              "company_name": "Acme", "company_domain": "boards.greenhouse.io/acme",
              "requisition_reference": "REQ-1", "title": "SWE"}
    lever_row = {"canonical_key": "lever::42",
                 "company_name": "Acme", "company_domain": "jobs.lever.co/acme",
                 "requisition_reference": "REQ-1", "title": "SWE"}
    k1 = compute_cluster_key(gh_row)
    k2 = compute_cluster_key(lever_row)
    assert k1 == k2, f"cross-source cluster key mismatch: {k1} vs {k2}"


def test_cluster_key_is_deterministic_and_case_normalized():
    r1 = {"canonical_key": "gh::1", "company_name": "Acme",
          "requisition_reference": "REQ-1", "title": "SWE"}
    r2 = {"canonical_key": "gh::1", "company_name": "  ACME  ",
          "requisition_reference": " req-1 ", "title": "SWE"}
    assert compute_cluster_key(r1) == compute_cluster_key(r2)


# ---------------------------------------------------------------- cluster ops
@pytest.mark.asyncio
async def test_upsert_cluster_member_is_idempotent():
    row = {"id": "job-1", "canonical_key": "greenhouse::1",
           "source_ats": "greenhouse", "company_name": "Acme",
           "requisition_reference": "REQ-42", "title": "SWE"}
    c1 = await upsert_cluster_member(row)
    c2 = await upsert_cluster_member(row)  # same row again — no dup member
    assert len(c1["members"]) == 1
    assert len(c2["members"]) == 1
    assert c1["cluster_key"] == c2["cluster_key"]


@pytest.mark.asyncio
async def test_cross_source_same_requisition_produces_one_cluster():
    """Two sources publishing the same requisition converge into one
    cluster. Dominant source is the ATS record (higher authority than
    the employer_intake copy)."""
    gh_row = {"id": "job-gh", "canonical_key": "greenhouse::1",
              "source_ats": "greenhouse", "company_name": "Acme",
              "requisition_reference": "REQ-42", "title": "SWE"}
    emp_row = {"id": "job-emp", "canonical_key": "employer_intake::1",
               "source_ats": "employer_intake", "company_name": "Acme",
               "requisition_reference": "REQ-42", "title": "SWE"}
    await upsert_cluster_member(gh_row)
    await upsert_cluster_member(emp_row)
    c = await cluster_for_job("job-gh")
    assert c is not None
    ids = {m["job_id"] for m in c["members"]}
    assert ids == {"job-gh", "job-emp"}
    assert c["dominant_source_id"] == "greenhouse"
    assert c["dominant_job_id"] == "job-gh"


@pytest.mark.asyncio
async def test_cluster_history_is_append_only_never_deletes():
    """The `cluster_history` field records every add_member event.
    Cluster docs are never deleted or overwritten."""
    row_a = {"id": "job-a", "source_ats": "greenhouse", "company_name": "X",
             "requisition_reference": "R", "title": "T"}
    row_b = {"id": "job-b", "source_ats": "lever", "company_name": "X",
             "requisition_reference": "R", "title": "T"}
    await upsert_cluster_member(row_a)
    c = await upsert_cluster_member(row_b)
    hist = c.get("cluster_history") or []
    # 1 create + 1 add_member.
    assert len(hist) == 2
    actions = [h["action"] for h in hist]
    assert actions == ["create", "add_member"]


# ---------------------------------------------------------------- dedup check
@pytest.mark.asyncio
async def test_dedup_check_finds_prior_receipt_via_cluster_member():
    """User submitted via source A → later reaches the same requisition
    via source B → `dedup_check` returns the prior receipt because both
    jobs belong to the same cluster."""
    from core.db import get_db
    db = get_db()

    row_a = {"id": "j-a", "source_ats": "greenhouse", "company_name": "Acme",
             "requisition_reference": "REQ-42", "title": "SWE"}
    row_b = {"id": "j-b", "source_ats": "ashby", "company_name": "Acme",
             "requisition_reference": "REQ-42", "title": "SWE"}
    await upsert_cluster_member(row_a)
    await upsert_cluster_member(row_b)

    # Prior submission was made via source A.
    receipt = {
        "id": str(uuid.uuid4()), "user_id": "test-er::user-1",
        "application_id": "app-1", "job_id": "j-a",
        "company_id": "acme", "req_ref": "gh::REQ-42",
        "supersedes": None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await db.submission_receipts.insert_one(receipt)

    # Second attempt reaches source B — must still detect the prior
    # submission.
    hit = await dedup_check("test-er::user-1", "j-b")
    assert hit is not None
    assert hit["job_id"] == "j-a"

    # Different user — no dedup hit (never leaks across users).
    other = await dedup_check("test-er::user-2", "j-b")
    assert other is None


@pytest.mark.asyncio
async def test_dedup_check_singleton_row_only_matches_itself():
    """A row with no clustering signal (no domain, no title) becomes a
    singleton — its dedup set is exactly {itself}. This is the safe
    default: never falsely dedup a user out of a real second app."""
    row = {"id": "j-solo", "source_ats": "unknown", "company_name": "",
           "title": "", "canonical_key": "row::solo"}
    await upsert_cluster_member(row)
    ids = await cluster_member_job_ids("j-solo")
    assert ids == ["j-solo"]


# ---------------------------------------------------------------- NO LLM
def test_entity_resolution_module_has_no_llm_calls():
    p = (pathlib.Path(__file__).resolve().parent.parent
         / "domains" / "entity_resolution" / "__init__.py")
    text = p.read_text(encoding="utf-8")
    forbidden = ("openai", "anthropic", "gemini",
                 "emergentintegrations", "generate_with_llm",
                 "chat.completions")
    hits = [f for f in forbidden if f in text.lower()]
    assert not hits, f"entity_resolution must NOT reference LLM SDKs: {hits}"

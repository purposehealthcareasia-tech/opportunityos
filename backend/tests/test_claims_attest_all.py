"""Phase 6b · attest-all + claim-set hash invariants.

Rails pinned:
  1. `attest_all` returns SHA-256 hash of a canonicalized claim set
     (sorted by id, JSON canonical for values). Deterministic — two
     users with the exact same claim set (impossible in practice, but
     algorithmically) produce the same hash.
  2. Hash is stable across attest-attest replays when the underlying
     claim set is unchanged.
  3. Editing a claim after attestation changes the hash on next attest.
  4. Consent ledger row is written with `scope="claims.attest_all"`,
     `attestation_hash`, `attested_count`, `newly_approved`.
  5. `no_claims_to_attest` short-circuit — empty user gets a graceful
     structured response (no hash, no consent row).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from core.db import get_db
from domains.claims import service as claims_svc
from domains.claims import repository as claims_repo


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


@pytest_asyncio.fixture
async def user_with_claims():
    """Seed a fresh test user with three claims of varying types."""
    uid = f"attest-test-{uuid.uuid4().hex[:12]}"
    db = get_db()
    now_claims = [
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "employment",
         "value": {"role": "Systems Engineer", "employer": "Acme"},
         "sensitivity": "normal", "status": "pending", "user_approved": False},
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "education",
         "value": {"school": "MIT", "degree": "BS"},
         "sensitivity": "normal", "status": "pending", "user_approved": False},
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "skill",
         "value": {"name": "Python"},
         "sensitivity": "normal", "status": "pending", "user_approved": False},
    ]
    from core.time_utils import utc_now
    now = utc_now()
    for c in now_claims:
        c["created_at"] = now
        c["updated_at"] = now
    await db.claims.insert_many(now_claims)
    yield uid, now_claims
    await db.claims.delete_many({"user_id": uid})
    await db.consent_records.delete_many({"user_id": uid})


@pytest.mark.asyncio
async def test_attest_all_returns_sha256_hash(user_with_claims):
    uid, seed = user_with_claims
    r = await claims_svc.attest_all(uid, policy_text_version="1.0")
    assert r["attested_count"] == 3
    assert r["newly_approved"] == 3
    assert set(r["newly_approved_ids"]) == {c["id"] for c in seed}
    h = r["claim_set_hash"]
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64
    # 2nd attest with no changes → same hash, zero new approvals.
    r2 = await claims_svc.attest_all(uid, policy_text_version="1.0")
    assert r2["claim_set_hash"] == h, "hash must be stable when claim set unchanged"
    assert r2["newly_approved"] == 0


@pytest.mark.asyncio
async def test_hash_changes_when_claim_edited(user_with_claims):
    uid, seed = user_with_claims
    r1 = await claims_svc.attest_all(uid, policy_text_version="1.0")
    h1 = r1["claim_set_hash"]
    # Edit one claim's value.
    edited_id = seed[0]["id"]
    await claims_repo.update_fields(edited_id, {"value": {"role": "Principal Engineer", "employer": "Acme"}})
    r2 = await claims_svc.attest_all(uid, policy_text_version="1.0")
    assert r2["claim_set_hash"] != h1, "editing a claim must change the hash"


@pytest.mark.asyncio
async def test_consent_row_written_with_hash(user_with_claims):
    uid, _ = user_with_claims
    r = await claims_svc.attest_all(uid, policy_text_version="1.0",
                                       source="unit-test")
    db = get_db()
    row = await db.consent_records.find_one({"id": r["consent_row_id"]})
    assert row is not None
    assert row["scope"] == "claims.attest_all"
    assert row["granted"] is True
    assert row["attestation_hash"] == r["claim_set_hash"]
    assert row["attested_count"] == 3
    assert row["newly_approved"] == 3
    assert row["policy_text_version"] == "1.0"
    assert row["source"] == "unit-test"


@pytest.mark.asyncio
async def test_empty_claims_short_circuits_gracefully():
    """User with no claims → structured graceful response, no consent row."""
    uid = f"empty-user-{uuid.uuid4().hex[:8]}"
    r = await claims_svc.attest_all(uid, policy_text_version="1.0")
    assert r["attested_count"] == 0
    assert r["claim_set_hash"] is None
    assert r["consent_row_id"] is None
    assert r["message"] == "no_claims_to_attest"
    db = get_db()
    n = await db.consent_records.count_documents({"user_id": uid})
    assert n == 0, "empty attest must NOT write a consent ledger row"

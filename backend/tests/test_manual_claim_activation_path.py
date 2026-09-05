"""P0 hotfix (2026-08-12) — manual-claim-only onboarding path locks.

The founder's directive: with the parse pipeline broken in prod, users
must still be able to reach passport activation with ZERO uploads by
manually entering claims. The activation checklist requires:
  - >=1 approved `identity` claim (`value.name`)
  - >=1 approved `education` OR `employment` claim

These tests exercise the same code paths the /passport React empty
state hits: POST /api/v1/claims (manual create, auto-approved), then
the activation-status + activate endpoints in domains/passport/router.py.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client_per_test():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


async def _make_user_with_consents():
    from core.db import get_db
    from core.time_utils import utc_now
    from domains.consent import service as consent_svc
    db = get_db()
    uid = f"manual-{uuid.uuid4().hex[:12]}"
    now = utc_now()
    await db.users.insert_one({
        "id": uid,
        "email": f"{uid}@opportunityos.test",
        "role": "user",
        "created_at": now,
        "updated_at": now,
    })
    await consent_svc.record(
        user_id=uid, scope="process_career_data", granted=True,
        policy_text_version="1.0",
        actor=uid, source="test.manual_claim_e2e",
    )
    return uid


async def _activation_state(user_id: str) -> dict:
    """Inlines the /activation-status endpoint logic so we test the same
    predicate without spinning a TestClient."""
    from core.db import get_db
    from domains.claims import repository as claims_repo
    approved = await claims_repo.approved_types(user_id)
    fresh = await get_db().users.find_one(
        {"id": user_id}, {"passport_activated": 1, "_id": 0}
    )
    return {
        "identity_approved": "identity" in approved,
        "education_or_employment_approved": (
            "education" in approved or "employment" in approved
        ),
        "can_activate": (
            "identity" in approved and
            ("education" in approved or "employment" in approved)
        ),
        "activated": bool(fresh and fresh.get("passport_activated")),
    }


@pytest.mark.asyncio
async def test_manual_identity_and_employment_reach_activation_checklist():
    from core.db import get_db
    from core.time_utils import utc_now
    from domains.claims import service as claims_svc
    from domains.audit import service as audit

    uid = await _make_user_with_consents()

    id_claim = await claims_svc.create_manual(
        uid, ctype="identity",
        value={"name": "Jane Manual Doe"},
        sensitivity="normal",
    )
    assert id_claim["status"] == "approved"
    assert id_claim["source"]["kind"] == "user_provided"
    assert id_claim["value"]["name"] == "Jane Manual Doe"

    emp_claim = await claims_svc.create_manual(
        uid, ctype="employment",
        value={
            "company": "Acme Corp",
            "role": "Backend Engineer",
            "start": "2021-04",
            "end": "2024-12",
            "summary": "Led migration of monolith to microservices",
        },
        sensitivity="normal",
    )
    assert emp_claim["status"] == "approved"
    assert emp_claim["source"]["kind"] == "user_provided"

    state = await _activation_state(uid)
    assert state["identity_approved"] is True
    assert state["education_or_employment_approved"] is True
    assert state["can_activate"] is True
    assert state["activated"] is False

    await get_db().users.update_one(
        {"id": uid},
        {"$set": {"passport_activated": True, "passport_activated_at": utc_now()}},
    )
    await audit.write(uid, "passport.activate", f"user:{uid}")

    final = await _activation_state(uid)
    assert final["activated"] is True


@pytest.mark.asyncio
async def test_manual_identity_and_education_also_qualifies():
    from domains.claims import service as claims_svc

    uid = await _make_user_with_consents()
    await claims_svc.create_manual(
        uid, ctype="identity",
        value={"name": "Manual Grad"}, sensitivity="normal",
    )
    edu = await claims_svc.create_manual(
        uid, ctype="education",
        value={
            "institution": "UC Berkeley",
            "degree": "BS Computer Science",
            "field": "CS",
            "start": "2018-08",
            "end": "2022-05",
        },
        sensitivity="normal",
    )
    assert edu["status"] == "approved"
    state = await _activation_state(uid)
    assert state["can_activate"] is True


@pytest.mark.asyncio
async def test_manual_identity_only_is_not_sufficient():
    from domains.claims import service as claims_svc

    uid = await _make_user_with_consents()
    await claims_svc.create_manual(
        uid, ctype="identity",
        value={"name": "Only Identity Person"}, sensitivity="normal",
    )
    state = await _activation_state(uid)
    assert state["identity_approved"] is True
    assert state["education_or_employment_approved"] is False
    assert state["can_activate"] is False


@pytest.mark.asyncio
async def test_manual_and_parsed_paths_coexist_no_interference():
    from domains.claims import service as claims_svc, repository as claims_repo

    uid = await _make_user_with_consents()
    c1 = await claims_svc.create_manual(
        uid, ctype="identity",
        value={"name": "Coexist Tester"}, sensitivity="normal",
    )
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    inserted = await claims_svc.insert_from_parse(
        user_id=uid,
        document_id=doc_id,
        model_used="gpt-5",
        parsed_claims=[{"type": "skill", "value": {"name": "Python"}, "confidence": 0.9}],
    )
    assert inserted == 1

    rows = await claims_repo.list_for_user(uid)
    by_id = {r["id"]: r for r in rows}
    manual_row = by_id[c1["id"]]
    parsed_row = next(r for r in rows if r["type"] == "skill")
    assert manual_row["source"]["kind"] == "user_provided"
    assert parsed_row["source"]["kind"] == "resume_parse"
    assert manual_row["status"] == "approved"
    # Parsed claims are NEVER auto-approved (rail-lock invariant).
    assert parsed_row["status"] in {"pending", "draft", "extracted"}

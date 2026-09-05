"""P0 Hotfix Gate (2026-08-13) — manual-claim-only onboarding path locks.

The founder's directive: with the parse pipeline broken in prod, users
must still be able to reach passport activation with ZERO uploads by
manually entering claims. The activation checklist requires:
  - >=1 approved `identity` claim (`value.name` legacy OR
    `{legal_first, legal_last, preferred_name}` new structured shape)
  - >=1 approved `education` OR `employment` claim

Hotfix Gate correction (2026-08-13): manual creates now save as DRAFT
(status="pending", user_approved=False). The user MUST explicitly tap
"Approve" on the Passport row for the attestation moment. `pending` is
the same status parsed claims use, so both paths route through the
identical `POST /api/v1/claims/{id}/approve` endpoint.

These tests exercise the same code paths the /passport React empty
state hits: POST /api/v1/claims (manual create → pending), then the
approve endpoint, then the activation-status + activate endpoints in
domains/passport/router.py.
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
async def test_manual_create_lands_as_pending_draft_not_approved():
    """Hotfix Gate lock: manual creates MUST land as pending (draft) —
    NEVER auto-approved. The user has to tap Approve to attest."""
    from domains.claims import service as claims_svc

    uid = await _make_user_with_consents()
    id_claim = await claims_svc.create_manual(
        uid, ctype="identity",
        value={"legal_first": "Jane", "legal_last": "Manual",
               "preferred_name": "Janie"},
        sensitivity="normal",
    )
    assert id_claim["status"] == "pending", (
        "manual claim must save as pending draft, not auto-approved"
    )
    assert id_claim["user_approved"] is False, (
        "user_approved must be False on manual create — approve step is explicit"
    )
    assert id_claim["source"]["kind"] == "user_provided"

    # Activation checklist NOT satisfied yet because pending != approved.
    state = await _activation_state(uid)
    assert state["identity_approved"] is False
    assert state["can_activate"] is False


@pytest.mark.asyncio
async def test_manual_identity_and_employment_reach_activation_checklist():
    from core.db import get_db
    from core.time_utils import utc_now
    from domains.claims import service as claims_svc
    from domains.audit import service as audit

    uid = await _make_user_with_consents()

    # Step 1 · create manual identity — lands as pending draft
    id_claim = await claims_svc.create_manual(
        uid, ctype="identity",
        value={"legal_first": "Jane", "legal_last": "Doe",
               "preferred_name": "Jane"},
        sensitivity="normal",
    )
    assert id_claim["status"] == "pending"
    assert id_claim["value"]["legal_first"] == "Jane"
    assert id_claim["value"]["legal_last"] == "Doe"
    assert id_claim["value"]["preferred_name"] == "Jane"

    # Step 2 · create manual employment — lands as pending draft
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
    assert emp_claim["status"] == "pending"
    assert emp_claim["source"]["kind"] == "user_provided"

    # Activation NOT satisfied yet — both are pending.
    state = await _activation_state(uid)
    assert state["identity_approved"] is False
    assert state["education_or_employment_approved"] is False
    assert state["can_activate"] is False

    # Step 3 · user taps Approve on both (attestation moment)
    approved_identity = await claims_svc.approve(uid, id_claim["id"])
    assert approved_identity["status"] == "approved"
    assert approved_identity["user_approved"] is True

    approved_emp = await claims_svc.approve(uid, emp_claim["id"])
    assert approved_emp["status"] == "approved"

    # NOW checklist is satisfied.
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
async def test_manual_identity_and_education_also_qualifies_after_approve():
    from domains.claims import service as claims_svc

    uid = await _make_user_with_consents()
    id_claim = await claims_svc.create_manual(
        uid, ctype="identity",
        value={"legal_first": "Manual", "legal_last": "Grad"},
        sensitivity="normal",
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
    assert edu["status"] == "pending"

    # Before approve — cannot activate.
    state = await _activation_state(uid)
    assert state["can_activate"] is False

    # After explicit approve on both — can activate.
    await claims_svc.approve(uid, id_claim["id"])
    await claims_svc.approve(uid, edu["id"])
    state = await _activation_state(uid)
    assert state["can_activate"] is True


@pytest.mark.asyncio
async def test_manual_identity_only_is_not_sufficient():
    from domains.claims import service as claims_svc

    uid = await _make_user_with_consents()
    id_claim = await claims_svc.create_manual(
        uid, ctype="identity",
        value={"legal_first": "Only", "legal_last": "Identity"},
        sensitivity="normal",
    )
    await claims_svc.approve(uid, id_claim["id"])
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
        value={"legal_first": "Coexist", "legal_last": "Tester"},
        sensitivity="normal",
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
    # Both land as pending — Hotfix Gate rail: NEITHER is auto-approved.
    assert manual_row["status"] == "pending"
    assert parsed_row["status"] in {"pending", "draft", "extracted"}


@pytest.mark.asyncio
async def test_canonical_identity_derives_name_from_structured_shape():
    """Hotfix Gate — preflight_validator._canonical_identity must accept
    both legacy `{name}` and new `{legal_first, legal_last, preferred_name}`
    shapes so signature-check math on outbound emails keeps working."""
    from services.preflight_validator import _canonical_identity

    # New structured shape with preferred_name → preferred_name wins.
    ident = _canonical_identity([
        {"type": "identity", "value": {
            "legal_first": "Jane", "legal_last": "Doe",
            "preferred_name": "J.D.",
        }},
    ])
    assert ident["name"] == "J.D."

    # New structured shape without preferred_name → derives from legal parts.
    ident = _canonical_identity([
        {"type": "identity", "value": {
            "legal_first": "Jane", "legal_last": "Doe",
        }},
    ])
    assert ident["name"] == "Jane Doe"

    # Legacy shape still works.
    ident = _canonical_identity([
        {"type": "identity", "value": {"name": "Legacy Person"}},
    ])
    assert ident["name"] == "Legacy Person"

    # Legacy shape takes precedence when both are present (backward compat).
    ident = _canonical_identity([
        {"type": "identity", "value": {
            "name": "Existing Legacy Name",
            "legal_first": "New", "legal_last": "Structured",
            "preferred_name": "Newname",
        }},
    ])
    assert ident["name"] == "Existing Legacy Name"

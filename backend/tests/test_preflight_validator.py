"""Pre-flight validator regression tests — Phase 5.0.

Locks in the founder rule (2026-07-28): "Zero unvalidated submissions by
construction — enforced at the dispatch chokepoint so no code path can
bypass it." Tests cover the module's public API (`preflight_check`,
`persist_verdict`, `block_and_route_to_review`) and also assert that both
existing dispatch chokepoints call the validator BEFORE writing any
outbound state.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_preflight_regression"


# --- 1. Static invariant: every dispatch chokepoint calls preflight_check --

DISPATCH_CHOKEPOINTS = (
    "/app/backend/domains/submit_sprint/__init__.py",
    "/app/backend/domains/email_route/__init__.py",
)


def test_every_dispatch_chokepoint_calls_preflight_before_receipt():
    """The `preflight_check(...)` call MUST appear before any
    `submission_receipts.insert_one(...)` and before any
    `email_outbox.insert_one(...)` in each chokepoint file."""
    for path in DISPATCH_CHOKEPOINTS:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        preflight_pos = src.find("preflight.preflight_check(")
        receipt_pos = src.find("submission_receipts.insert_one(")
        outbox_pos = src.find("email_outbox.insert_one(")
        assert preflight_pos != -1, f"{path} does not call preflight.preflight_check(...)"
        if receipt_pos != -1:
            assert preflight_pos < receipt_pos, (
                f"{path}: preflight_check must run BEFORE "
                f"submission_receipts.insert_one (got preflight@{preflight_pos}, "
                f"receipt@{receipt_pos})")
        if outbox_pos != -1:
            assert preflight_pos < outbox_pos, (
                f"{path}: preflight_check must run BEFORE "
                f"email_outbox.insert_one (got preflight@{preflight_pos}, "
                f"outbox@{outbox_pos})")


def test_every_dispatch_chokepoint_blocks_on_unwilling_verdict():
    """Each chokepoint must raise HTTPException(422) or route to review on
    a `verdict.ok=False` outcome — we detect this by requiring the
    verdict-ok branch and the block-and-raise pattern to both appear in
    the file."""
    for path in DISPATCH_CHOKEPOINTS:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "if not verdict.ok" in src, (
            f"{path}: missing `if not verdict.ok:` block guarding outbound write.")
        assert "block_and_route_to_review" in src, (
            f"{path}: verdict blocks must go through preflight.block_and_route_to_review")
        assert "HTTP_422_UNPROCESSABLE_ENTITY" in src, (
            f"{path}: verdict blocks must return HTTP 422 to the client.")


def test_every_dispatch_chokepoint_embeds_verdict_on_receipt():
    """When the verdict passes, the receipt written to submission_receipts
    MUST embed the verdict.compact() under key `validator_verdict` — that
    is the receipt's proof of chokepoint clearance."""
    for path in DISPATCH_CHOKEPOINTS:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if "submission_receipts.insert_one" not in src:
            continue
        assert '"validator_verdict": verdict.compact()' in src, (
            f"{path}: submission_receipts row missing "
            f"'validator_verdict': verdict.compact() field.")


# --- 2. Functional tests ----------------------------------------------------


@pytest.fixture
async def scratch_db(monkeypatch):
    """Isolated scratch DB (`oppos_test_preflight_regression`). Every test
    gets a fresh Motor client so pytest-asyncio's per-test event loop
    doesn't strand a previously-cached one."""
    from core import db as core_db

    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    scratch = client[DB_NAME]
    for cn in ("claims", "resume_versions", "applications",
                 "preflight_verdicts", "audit_logs"):
        await scratch.drop_collection(cn)

    original_get = core_db.get_db
    monkeypatch.setattr(core_db, "get_db", lambda: scratch)
    try:
        yield scratch
    finally:
        monkeypatch.setattr(core_db, "get_db", original_get)
        for cn in ("claims", "resume_versions", "applications",
                     "preflight_verdicts", "audit_logs"):
            await scratch.drop_collection(cn)
        client.close()


async def _seed(scratch, *, approved: bool = True, with_manifest: bool = True,
                 line_text: str = "Systems Engineer at Fixture Motors 2021-2022.",
                 add_bad_line: bool = False, name: str = "Fixture TestUser") -> dict:
    """Create a user + approved claim(s) + base resume manifest.
    Returns dict with user_id + application_id + expected_manifest_hash."""
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    app_id = f"app-{uuid.uuid4().hex[:8]}"

    identity_id = str(uuid.uuid4())
    experience_id = str(uuid.uuid4())
    await scratch.claims.insert_many([
        {"id": identity_id, "user_id": user_id, "type": "identity",
         "value": {"name": name, "email": f"{name.replace(' ','.').lower()}@fixture.dev"},
         "sensitivity": "normal", "status": "approved" if approved else "pending",
         "user_approved": True},
        {"id": experience_id, "user_id": user_id, "type": "experience",
         "value": {"role": "Systems Engineer", "employer": "Fixture Motors",
                   "start": "2021", "end": "2022"},
         "sensitivity": "normal", "status": "approved" if approved else "pending",
         "user_approved": True},
    ])
    if with_manifest:
        lines = [{"line_id": str(uuid.uuid4()), "text": line_text,
                    "claim_ids": [experience_id], "status": "accepted"}]
        if add_bad_line:
            # Bad line: fake numeric claim not present in claims.
            lines.append({"line_id": str(uuid.uuid4()),
                            "text": "Increased throughput by 9999x in 2015.",
                            "claim_ids": [experience_id], "status": "accepted"})
        await scratch.resume_versions.insert_one({
            "id": str(uuid.uuid4()), "user_id": user_id, "application_id": None,
            "base": True, "name": "base",
            "render_manifest": {"lines": lines},
        })
    await scratch.applications.insert_one({
        "id": app_id, "user_id": user_id, "state": "shortlisted",
        "materials": {},
    })
    return {"user_id": user_id, "application_id": app_id,
            "identity_id": identity_id, "experience_id": experience_id}


@pytest.mark.asyncio
async def test_preflight_passes_for_clean_traceable_materials(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db)
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_SPRINT_FIXTURE,
    )
    assert verdict.ok is True, verdict.reasons
    assert verdict.reasons == []
    assert verdict.line_stats["passed"] == 1
    assert verdict.line_stats["rejected"] == 0


@pytest.mark.asyncio
async def test_preflight_blocks_when_user_has_no_approved_claims(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db, approved=False)
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_SPRINT_FIXTURE,
    )
    assert verdict.ok is False
    assert pf.REASON_NO_APPROVED_CLAIMS in verdict.reasons
    assert pf.REASON_TOP_LEVEL in verdict.reasons


@pytest.mark.asyncio
async def test_preflight_blocks_when_no_materials(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db, with_manifest=False)
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_SPRINT_FIXTURE,
    )
    assert verdict.ok is False
    assert pf.REASON_NO_MATERIALS in verdict.reasons


@pytest.mark.asyncio
async def test_preflight_blocks_on_untraceable_number(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db, add_bad_line=True)
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_SPRINT_FIXTURE,
    )
    assert verdict.ok is False
    joined = " ".join(verdict.reasons)
    assert "line_validation_failed" in joined
    assert verdict.line_stats["rejected"] >= 1


@pytest.mark.asyncio
async def test_preflight_email_route_blocks_on_signature_mismatch(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db, name="Fixture TestUser")
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_EMAIL_DRY_RUN,
        outbound_fields={
            "destination": "employer@example.com",
            "subject": "Application",
            # Sign-off name doesn't match Passport identity.
            "body": "Please review. Sincerely, Impostor Name",
        },
    )
    assert verdict.ok is False
    assert pf.REASON_IDENTITY_MISMATCH in verdict.reasons


@pytest.mark.asyncio
async def test_preflight_email_route_blocks_on_third_party_email_in_body(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db, name="Fixture TestUser")
    # Passport identity email is fixture.testuser@fixture.dev — third-party
    # email in body triggers an identity block.
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_EMAIL_DRY_RUN,
        outbound_fields={
            "destination": "employer@example.com",
            "subject": "Application",
            "body": "Please review. Contact me at foreign@rogue.com",
        },
    )
    assert verdict.ok is False
    assert pf.REASON_IDENTITY_MISMATCH in verdict.reasons


@pytest.mark.asyncio
async def test_preflight_email_route_blocks_on_ungrounded_number_in_subject(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db)
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_EMAIL_DRY_RUN,
        outbound_fields={
            "destination": "employer@example.com",
            # 12345 is not in any approved claim → block.
            "subject": "Application id 12345",
            "body": "Please review.",
        },
    )
    assert verdict.ok is False
    assert any("number_not_in_claims" in r for r in verdict.reasons)


@pytest.mark.asyncio
async def test_preflight_email_route_passes_with_traceable_subject_and_signature(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db, name="Fixture TestUser")
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_EMAIL_DRY_RUN,
        outbound_fields={
            "destination": "employer@example.com",
            "subject": "Application",
            "body": "Please consider my application. Sincerely, Fixture TestUser",
        },
    )
    assert verdict.ok is True, verdict.reasons


@pytest.mark.asyncio
async def test_preflight_unknown_channel_raises_valueerror(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db)
    with pytest.raises(ValueError):
        await pf.preflight_check(
            user_id=ctx["user_id"], application_id=ctx["application_id"],
            channel="unknown_channel_xyz",
        )


@pytest.mark.asyncio
async def test_block_and_route_to_review_moves_application_state(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db, approved=False)
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_EMAIL_DRY_RUN,
    )
    assert verdict.ok is False
    await pf.block_and_route_to_review(verdict, audit_actor=ctx["user_id"])
    app = await scratch_db.applications.find_one(
        {"id": ctx["application_id"]}, {"_id": 0, "state": 1, "review_reason": 1})
    assert app["state"] == "review"
    assert app["review_reason"] == pf.REASON_TOP_LEVEL

    persisted = await scratch_db.preflight_verdicts.find_one(
        {"id": verdict.id}, {"_id": 0})
    assert persisted is not None
    assert persisted["ok"] is False


@pytest.mark.asyncio
async def test_preflight_manifest_hash_mismatch_blocks(scratch_db):
    from services import preflight_validator as pf

    ctx = await _seed(scratch_db)
    verdict = await pf.preflight_check(
        user_id=ctx["user_id"], application_id=ctx["application_id"],
        channel=pf.CHANNEL_SPRINT_FIXTURE,
        expected_manifest_hash="sha256:this-is-not-the-actual-hash",
    )
    assert verdict.ok is False
    assert pf.REASON_MANIFEST_MISMATCH in verdict.reasons

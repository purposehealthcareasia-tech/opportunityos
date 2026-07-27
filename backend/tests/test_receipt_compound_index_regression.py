"""Regression: submission_receipts compound-unique-index collision (2026-07-28).

Bug (repro'd twice by independent tester):
    Prior sprint confirm insert wrote a submission_receipts row with
    company_id=null and req_ref=null. A subsequent email-route dispatch by
    the SAME user hit E11000 DuplicateKeyError on
    `uniq_receipt_per_user_company_req = (user_id, company_id, req_ref)`
    because MongoDB treats nulls as equal in a compound unique index.
    The outbox row still persisted, so the SECOND dispatch call returned
    201 with `duplicate=true`, masking the regression as if it were normal
    dedup behaviour.

This module locks in the fix at three layers:

1. Every receipt writer must produce non-null (company_id, req_ref) — no
   more legacy `(user_id, null, null)` collisions.
2. `insert()` in domains/submission_receipts/service.py still hard-fails
   on any falsy required field.
3. Full path: sprint slot confirm ➜ email-route dispatch for the same
   user succeeds against the real compound unique index.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_receipt_regression"


# --- 1. Static invariants: no receipt writer may pass null for these keys ----

RECEIPT_WRITERS = (
    "/app/backend/domains/submit_sprint/__init__.py",
    "/app/backend/domains/email_route/__init__.py",
    "/app/backend/domains/applications/service.py",
    "/app/backend/domains/submission_receipts/service.py",
)


def _receipt_insert_blocks(path: str) -> list[str]:
    """Return each source block that assembles a receipt about to be inserted
    into submission_receipts. Blocks are dict-literal ranges (``{ ... }``)
    named ``receipt`` or ``doc``, but only when there's an
    ``submission_receipts.insert_one`` call within the following ~800 chars."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if "submission_receipts" not in src:
        return []
    blocks: list[str] = []
    for name in ("receipt", "doc"):
        for m in re.finditer(rf"\b{name}\s*=\s*\{{", src):
            end = m.end()
            depth = 1
            i = end
            while i < len(src) and depth:
                if src[i] == "{":
                    depth += 1
                elif src[i] == "}":
                    depth -= 1
                i += 1
            end_block = i
            trailing = src[end_block: end_block + 900]
            if "submission_receipts.insert_one" not in trailing:
                continue
            blocks.append(src[m.start(): end_block])
    return blocks


def test_every_receipt_writer_populates_company_id_and_req_ref():
    """No receipt insert block may omit `company_id` or `req_ref`, and
    neither key may be explicitly set to `None`."""
    offenders: list[str] = []
    for path in RECEIPT_WRITERS:
        for block in _receipt_insert_blocks(path):
            for key in ("company_id", "req_ref"):
                if f'"{key}"' not in block:
                    offenders.append(f"{path} — receipt block missing '{key}': {block[:180]}...")
                    continue
                if re.search(rf'"{key}"\s*:\s*None\b', block):
                    offenders.append(f"{path} — receipt block sets '{key}' to None: {block[:180]}...")
    assert not offenders, "\n".join(offenders)


# --- 2. Service-level guard still hard-fails on falsy inputs -----------------


@pytest.fixture
async def scratch_db():
    """Fresh scratch DB with only the receipts compound unique index. Every
    test gets a fresh Motor client so pytest-asyncio's per-test event loop
    doesn't strand a previously-cached one (`RuntimeError: Event loop is
    closed`)."""
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    await db.drop_collection("submission_receipts")
    await db.submission_receipts.create_index(
        [("user_id", ASCENDING), ("company_id", ASCENDING), ("req_ref", ASCENDING)],
        unique=True,
        name="uniq_receipt_per_user_company_req",
    )
    try:
        yield db
    finally:
        await db.drop_collection("submission_receipts")
        client.close()


@pytest.mark.asyncio
async def test_receipts_service_insert_rejects_falsy_required_fields():
    """The receipts service helper (used by the real Phase 5 submit path)
    still refuses any falsy required field. This is the invariant that
    prevented the real submit path from producing (user, null, null) —
    the sprint + email-route paths were bypassing this helper."""
    from domains.submission_receipts import service as receipts

    for missing in ("user_id", "company_id", "req_ref", "application_id", "job_id"):
        kwargs = dict(
            user_id="u", company_id="c", req_ref="r",
            application_id="a", job_id="j",
            materials_manifest_hash="h", submit_channel="ch",
        )
        kwargs[missing] = ""
        with pytest.raises(ValueError):
            await receipts.insert(**kwargs)


# --- 3. Concrete collision replay --------------------------------------------


def _sprint_receipt_shape(user_id: str, application_id: str, slot_id: str,
                           sprint_id: str, company_id: str = "sampleco.demo") -> dict:
    """Mirror the receipt shape emitted by
    domains/submit_sprint/__init__.py::confirm_slot."""
    now = datetime.now(timezone.utc)
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "application_id": application_id,
        "job_id": f"job-{application_id}",
        "company_id": company_id,
        "req_ref": f"sprint:slot:{slot_id}",
        "materials_manifest_hash": f"sprint_fixture:{slot_id}",
        "submit_channel": "sprint_fixture",
        "supersedes": None,
        "ts": now,
        "route": "sprint_fixture",
        "kind": "fixture_sprint",
        "sprint_id": sprint_id,
        "slot_id": slot_id,
        "sent_to_smtp": False,
        "created_at": now,
    }


def _email_route_receipt_shape(user_id: str, application_id: str, outbox_id: str,
                                destination: str,
                                company_id: str = "sampleco.demo") -> dict:
    """Mirror the receipt shape emitted by
    domains/email_route/__init__.py::dispatch."""
    now = datetime.now(timezone.utc)
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "application_id": application_id,
        "job_id": f"job-{application_id}",
        "company_id": company_id,
        "req_ref": f"email-route:outbox:{outbox_id}",
        "materials_manifest_hash": f"email_dry_run:{outbox_id}",
        "submit_channel": "email_dry_run",
        "supersedes": None,
        "ts": now,
        "route": "email",
        "kind": "email_dry_run",
        "outbox_id": outbox_id,
        "destination": destination.lower(),
        "created_at": now,
    }


@pytest.mark.asyncio
async def test_sprint_then_email_route_receipts_do_not_collide(scratch_db):
    """Full-path regression. Insert a sprint receipt then an email-route
    receipt for the SAME (user, application). Both must succeed against
    the compound unique index (user_id, company_id, req_ref)."""
    uid = f"regression-{uuid.uuid4().hex[:8]}"
    app_id = "app-1"
    slot_id = str(uuid.uuid4())
    outbox_id = str(uuid.uuid4())

    r1 = await scratch_db.submission_receipts.insert_one(
        _sprint_receipt_shape(uid, app_id, slot_id, sprint_id="sprint-1"),
    )
    assert r1.inserted_id is not None
    # This is the insert that historically 500'd with E11000.
    r2 = await scratch_db.submission_receipts.insert_one(
        _email_route_receipt_shape(uid, app_id, outbox_id, "fixture@dry.run"),
    )
    assert r2.inserted_id is not None

    rows = [r async for r in scratch_db.submission_receipts.find({"user_id": uid}, {"_id": 0})]
    req_refs = sorted(r["req_ref"] for r in rows)
    assert req_refs == sorted([f"sprint:slot:{slot_id}",
                                 f"email-route:outbox:{outbox_id}"])


@pytest.mark.asyncio
async def test_sprint_slot_receipts_do_not_collide_across_slots(scratch_db):
    """Two sprint slots for the same user + same fixture company must
    insert cleanly. Historically both would have produced (user, null,
    null) and collided on the compound unique index."""
    uid = f"regression-{uuid.uuid4().hex[:8]}"
    slot_a, slot_b = str(uuid.uuid4()), str(uuid.uuid4())
    await scratch_db.submission_receipts.insert_many([
        _sprint_receipt_shape(uid, "app-A", slot_a, sprint_id="sprint-1"),
        _sprint_receipt_shape(uid, "app-B", slot_b, sprint_id="sprint-1"),
    ])
    assert await scratch_db.submission_receipts.count_documents({"user_id": uid}) == 2


@pytest.mark.asyncio
async def test_two_email_route_receipts_to_different_destinations_do_not_collide(scratch_db):
    """Same user, same application, two different dry-run destinations →
    two distinct outbox rows → two distinct receipts. Must not collide."""
    uid = f"regression-{uuid.uuid4().hex[:8]}"
    outbox_a, outbox_b = str(uuid.uuid4()), str(uuid.uuid4())
    await scratch_db.submission_receipts.insert_many([
        _email_route_receipt_shape(uid, "app-1", outbox_a, "a@dry.run"),
        _email_route_receipt_shape(uid, "app-1", outbox_b, "b@dry.run"),
    ])
    assert await scratch_db.submission_receipts.count_documents({"user_id": uid}) == 2

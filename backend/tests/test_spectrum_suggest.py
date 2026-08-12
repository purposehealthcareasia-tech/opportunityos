"""Phase 6b · auto-spectrum suggestion invariants.

Rails pinned:
* Titles from approved role/experience claims only (unapproved ignored).
* Radius default 25 mi.
* Pay floor: MEDIAN of last-2-years VERIFIED compensation rows only.
* When no verified comp history exists, `pay_floor is None` and rationale
  says so explicitly — never invented.
* Superseded claims ignored.
* Empty user → all-empty response with explicit rationales.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from core.db import get_db
from core.time_utils import utc_now
from domains.spectrum import service as spectrum_svc


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


@pytest_asyncio.fixture
async def user_with_passport():
    """Seed a user with approved role/experience claims and mixed comp."""
    uid = f"spectrum-{uuid.uuid4().hex[:12]}"
    db = get_db()
    now = utc_now()
    this_year = datetime.now(timezone.utc).year
    docs = [
        # Approved role claim — should surface as first title.
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "role",
         "value": {"role": "Systems Engineer"}, "sensitivity": "normal",
         "status": "approved", "user_approved": True,
         "created_at": now, "updated_at": now},
        # Approved experience claim.
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "experience",
         "value": {"role": "Backend Engineer", "employer": "Acme"},
         "sensitivity": "normal", "status": "approved", "user_approved": True,
         "created_at": now, "updated_at": now},
        # Pending (NOT approved) — must be excluded.
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "role",
         "value": {"role": "IGNORE_ME_UNAPPROVED"}, "sensitivity": "normal",
         "status": "pending", "user_approved": False,
         "created_at": now, "updated_at": now},
        # Verified comp within the 2-year window.
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "compensation",
         "value": {"annual_usd": 145000, "verified": True, "end_year": this_year - 1},
         "sensitivity": "normal", "status": "approved", "user_approved": True,
         "created_at": now, "updated_at": now},
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "compensation",
         "value": {"annual_usd": 165000, "verified": True, "end_year": this_year},
         "sensitivity": "normal", "status": "approved", "user_approved": True,
         "created_at": now, "updated_at": now},
        # UN-verified comp — must be excluded from pay_floor median.
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "compensation",
         "value": {"annual_usd": 500000, "verified": False, "end_year": this_year},
         "sensitivity": "normal", "status": "approved", "user_approved": True,
         "created_at": now, "updated_at": now},
    ]
    await db.claims.insert_many(docs)
    yield uid
    await db.claims.delete_many({"user_id": uid})


@pytest.mark.asyncio
async def test_suggest_titles_only_from_approved_claims(user_with_passport):
    r = await spectrum_svc.suggest_spectrum(user_with_passport)
    titles_lc = [t.lower() for t in r["titles"]]
    assert "systems engineer" in titles_lc
    assert "backend engineer" in titles_lc
    # Unapproved claim MUST NOT surface.
    assert not any("ignore_me" in t.lower() for t in r["titles"])


@pytest.mark.asyncio
async def test_pay_floor_uses_verified_history_median(user_with_passport):
    r = await spectrum_svc.suggest_spectrum(user_with_passport)
    # Verified rows are 145000, 165000 → median = 155000.
    assert r["pay_floor"] == 155000
    assert r["rationale"]["pay_floor"].startswith("median of 2 verified")


@pytest.mark.asyncio
async def test_pay_floor_never_invented_when_no_verified():
    """User with unverified comp only → pay_floor is None with explicit
    'no_verified_history' rationale (never a fabricated number)."""
    uid = f"spectrum-{uuid.uuid4().hex[:12]}"
    db = get_db()
    await db.claims.insert_one({
        "id": str(uuid.uuid4()), "user_id": uid, "type": "compensation",
        "value": {"annual_usd": 200000, "verified": False, "end_year": 2026},
        "sensitivity": "normal", "status": "approved", "user_approved": True,
        "created_at": utc_now(), "updated_at": utc_now(),
    })
    try:
        r = await spectrum_svc.suggest_spectrum(uid)
        assert r["pay_floor"] is None
        assert r["rationale"]["pay_floor"] == "no_verified_history"
    finally:
        await db.claims.delete_many({"user_id": uid})


@pytest.mark.asyncio
async def test_empty_user_gets_all_empty_with_rationale():
    uid = f"spectrum-empty-{uuid.uuid4().hex[:8]}"
    r = await spectrum_svc.suggest_spectrum(uid)
    assert r["titles"] == []
    assert r["radius_mi"] == 25
    assert r["pay_floor"] is None
    assert r["rationale"]["titles_source"] == "no_approved_role_or_experience_claims"
    assert r["rationale"]["pay_floor"] == "no_verified_history"
    assert r["honest_label"] == "suggested from your Passport — edit anytime"


@pytest.mark.asyncio
async def test_superseded_claims_ignored():
    uid = f"spectrum-supers-{uuid.uuid4().hex[:8]}"
    db = get_db()
    now = utc_now()
    await db.claims.insert_many([
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "role",
         "value": {"role": "OLD_TITLE"}, "sensitivity": "normal",
         "status": "approved", "user_approved": True,
         "superseded_by": "some-new-id",
         "created_at": now, "updated_at": now},
        {"id": str(uuid.uuid4()), "user_id": uid, "type": "role",
         "value": {"role": "NEW_TITLE"}, "sensitivity": "normal",
         "status": "approved", "user_approved": True,
         "created_at": now, "updated_at": now},
    ])
    try:
        r = await spectrum_svc.suggest_spectrum(uid)
        titles = [t.upper() for t in r["titles"]]
        assert "NEW_TITLE" in titles
        assert "OLD_TITLE" not in titles
    finally:
        await db.claims.delete_many({"user_id": uid})

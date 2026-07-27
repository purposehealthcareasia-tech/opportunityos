"""Outcome autopilot regression tests — Phase 5.3."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_outcome_autopilot"


@pytest.fixture
async def scratch_db(monkeypatch):
    from core import db as core_db
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    for cn in ("applications", "application_outcomes",
                 "budget_reallocations", "kill_list"):
        await db.drop_collection(cn)
    monkeypatch.setattr(core_db, "get_db", lambda: db)
    try:
        yield db
    finally:
        for cn in ("applications", "application_outcomes",
                     "budget_reallocations", "kill_list"):
            await db.drop_collection(cn)
        client.close()


async def _seed_app(scratch, user_id: str, employer: str,
                     submitted_at: datetime, resume_version_id: str | None = None,
                     ) -> str:
    app_id = f"app-{uuid.uuid4().hex[:8]}"
    await scratch.applications.insert_one({
        "id": app_id, "user_id": user_id,
        "company_id": employer,
        "materials": {"resume_version_id": resume_version_id},
        "job_snapshot": {"canonical_key": f"{employer}::role"},
        "submitted_at": submitted_at,
        "created_at": submitted_at,
    })
    return app_id


@pytest.mark.asyncio
async def test_record_outcome_rejects_unknown_kind(scratch_db):
    from services import outcome_autopilot as oa
    with pytest.raises(ValueError):
        await oa.record_outcome(application_id="a", user_id="u",
                                    kind="ghosted")


@pytest.mark.asyncio
async def test_group_stats_response_rate_and_median_days(scratch_db):
    from services import outcome_autopilot as oa
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    # ACME: 3 apps, 2 responses (day 4 + day 6), 1 silence.
    a1 = await _seed_app(scratch_db, user_id, "acme", now - timedelta(days=7))
    a2 = await _seed_app(scratch_db, user_id, "acme", now - timedelta(days=8))
    a3 = await _seed_app(scratch_db, user_id, "acme", now - timedelta(days=9))
    await oa.record_outcome(application_id=a1, user_id=user_id,
                                kind=oa.OUTCOME_RESPONSE,
                                at=now - timedelta(days=3))
    await oa.record_outcome(application_id=a2, user_id=user_id,
                                kind=oa.OUTCOME_RESPONSE,
                                at=now - timedelta(days=2))
    await oa.record_outcome(application_id=a3, user_id=user_id,
                                kind=oa.OUTCOME_SILENCE, at=now)

    # BETA: 2 apps, 0 responses, 2 silences.
    b1 = await _seed_app(scratch_db, user_id, "beta", now - timedelta(days=7))
    b2 = await _seed_app(scratch_db, user_id, "beta", now - timedelta(days=8))
    await oa.record_outcome(application_id=b1, user_id=user_id,
                                kind=oa.OUTCOME_SILENCE, at=now)
    await oa.record_outcome(application_id=b2, user_id=user_id,
                                kind=oa.OUTCOME_SILENCE, at=now)

    stats = await oa.compute_group_stats(user_id, since_days=30)
    assert set(stats.keys()) == {"acme", "beta"}
    acme = stats["acme"]
    assert acme["submitted"] == 3
    assert acme["response"] == 2
    assert acme["silence"] == 1
    assert acme["response_rate"] == round(2 / 3, 3)
    # median days-to-response = median(4, 6) = 5.
    assert acme["median_days_to_response"] == 5.0
    beta = stats["beta"]
    assert beta["submitted"] == 2
    assert beta["response_rate"] == 0.0
    assert beta["median_days_to_response"] is None


@pytest.mark.asyncio
async def test_reallocate_shifts_budget_toward_responders(scratch_db):
    from services import outcome_autopilot as oa
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    # High responder + low responder.
    for _ in range(5):
        aid = await _seed_app(scratch_db, user_id, "high", now - timedelta(days=10))
        await oa.record_outcome(application_id=aid, user_id=user_id,
                                    kind=oa.OUTCOME_RESPONSE, at=now)
    for _ in range(5):
        aid = await _seed_app(scratch_db, user_id, "low", now - timedelta(days=10))
        await oa.record_outcome(application_id=aid, user_id=user_id,
                                    kind=oa.OUTCOME_SILENCE, at=now)
    reallocation = await oa.reallocate_daily_budget(user_id, since_days=30,
                                                        min_group_submits=3)
    groups = {a["group"]: a for a in reallocation["allocations"]}
    assert set(groups.keys()) == {"high", "low"}
    assert groups["high"]["weight"] > groups["low"]["weight"]
    # Reason must be present + human-readable.
    assert "response_rate" in groups["high"]["reason"]


@pytest.mark.asyncio
async def test_kill_list_candidates_identifies_silent_employers(scratch_db):
    from services import outcome_autopilot as oa
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    for _ in range(6):
        aid = await _seed_app(scratch_db, user_id, "ghosts",
                                now - timedelta(days=10))
        await oa.record_outcome(application_id=aid, user_id=user_id,
                                    kind=oa.OUTCOME_SILENCE, at=now)
    # Also an active-responder employer that SHOULD NOT show up.
    for _ in range(3):
        aid = await _seed_app(scratch_db, user_id, "warm",
                                now - timedelta(days=10))
        await oa.record_outcome(application_id=aid, user_id=user_id,
                                    kind=oa.OUTCOME_VIEWED, at=now)

    candidates = await oa.kill_list_candidates(
        user_id, silence_threshold=5, silence_days=21)
    tokens = [c["employer"] for c in candidates]
    assert "ghosts" in tokens
    assert "warm" not in tokens


@pytest.mark.asyncio
async def test_kill_list_add_and_restore_is_idempotent_and_reversible(scratch_db):
    from services import outcome_autopilot as oa
    user_id = f"u"
    r1 = await oa.add_to_kill_list(user_id, "acme", reason="test")
    r2 = await oa.add_to_kill_list(user_id, "acme", reason="test-duplicate")
    # Idempotent — second call returns the SAME row.
    assert r1["id"] == r2["id"]
    restored = await oa.restore_from_kill_list(user_id, "acme",
                                                  restored_reason="user_click")
    assert restored is not None
    assert restored["restored_reason"] == "user_click"
    assert restored["restored_at"] is not None
    # Second restore returns None — nothing active.
    assert await oa.restore_from_kill_list(user_id, "acme") is None

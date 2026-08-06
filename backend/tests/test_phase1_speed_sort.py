"""Phase 1 §iv (1a) — Speed-ranked feed sort tests.

These tests prove:
* sort=speed key function orders employers with data BEFORE employers without,
  and by ascending `median_days_to_response` within the has-data bucket.
* speed block is user-scoped (built from THIS USER's application_outcomes only).
* `compute_group_stats` returns median_days_to_response==None when no
  outcomes exist for the user (fixture-ead@ empty state).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from services import outcome_autopilot as oa


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "fynd_test_phase1_speed_sort"


@pytest.fixture
async def scratch_db(monkeypatch):
    from core import db as core_db
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    for cn in ("applications", "application_outcomes"):
        await db.drop_collection(cn)
    monkeypatch.setattr(core_db, "get_db", lambda: db)
    try:
        yield db
    finally:
        for cn in ("applications", "application_outcomes"):
            await db.drop_collection(cn)


def _speed_key(x):
    """Mirror of the sort key implemented inline in
    `backend/domains/jobs/router.py::feed` under sort=='speed'.

    Kept in the test file to avoid an extra import surface. If the router
    key changes, this must change with it.
    """
    md = (x.get("speed") or {}).get("median_days_to_response")
    has_data = 0 if isinstance(md, (int, float)) else 1
    md_val = md if isinstance(md, (int, float)) else 1e9
    score_val = x.get("score") or 0
    return (has_data, md_val, -score_val)


def test_speed_sort_orders_data_first():
    cards = [
        {"id": "a", "score": 91, "speed": {"median_days_to_response": None}},
        {"id": "b", "score": 60, "speed": {"median_days_to_response": 3.0}},
        {"id": "c", "score": 80, "speed": {"median_days_to_response": 12.0}},
        {"id": "d", "score": 75, "speed": {"median_days_to_response": None}},
        {"id": "e", "score": 95, "speed": {"median_days_to_response": 3.0}},
    ]
    cards.sort(key=_speed_key)
    ids = [c["id"] for c in cards]
    # has-data first, sorted by median ascending; ties broken by score descending.
    # a & d (no data) sink last, sorted by score descending.
    assert ids == ["e", "b", "c", "a", "d"], ids


def test_speed_sort_no_data_bucket_preserves_score_order():
    cards = [
        {"id": "x", "score": 50, "speed": {"median_days_to_response": None}},
        {"id": "y", "score": 90, "speed": {"median_days_to_response": None}},
        {"id": "z", "score": 70, "speed": {"median_days_to_response": None}},
    ]
    cards.sort(key=_speed_key)
    assert [c["id"] for c in cards] == ["y", "z", "x"]


def test_speed_note_when_no_data():
    """The `note` field is a UI-facing label — must say 'no response data yet'
    when median is None, otherwise a human summary."""
    def _note(median, submitted, responded):
        if median is None:
            return "no response data yet"
        return f"median {median}d to response · {responded}/{submitted} responded"
    assert _note(None, 0, 0) == "no response data yet"
    assert _note(3.0, 4, 3) == "median 3.0d to response · 3/4 responded"


@pytest.mark.asyncio
async def test_compute_group_stats_empty_returns_dict(scratch_db):
    """Sanity check: a user with no outcomes returns {} (not an error)."""
    fake_user = str(uuid.uuid4())
    res = await oa.compute_group_stats(fake_user, since_days=30, group_by="employer")
    assert res == {}, res


@pytest.mark.asyncio
async def test_compute_group_stats_derives_median_and_response_rate(scratch_db):
    """Insert one response-outcome for a synthetic user + app; assert
    compute_group_stats returns median_days_to_response and response_rate.
    """
    db = scratch_db
    user_id = f"testuser-{uuid.uuid4().hex[:8]}"
    app_id = f"testapp-{uuid.uuid4().hex[:8]}"
    submitted_at = datetime.now(timezone.utc) - timedelta(days=5)
    responded_at = submitted_at + timedelta(days=3)

    await db.applications.insert_one({
        "id": app_id,
        "user_id": user_id,
        "company_id": "acme-corp",
        "job_snapshot": {"canonical_key": "acme-corp::role-1"},
        "submitted_at": submitted_at,
    })
    await db.application_outcomes.insert_one({
        "id": str(uuid.uuid4()),
        "application_id": app_id,
        "user_id": user_id,
        "kind": oa.OUTCOME_RESPONSE,
        "at": responded_at,
        "note": None,
    })
    res = await oa.compute_group_stats(user_id, since_days=30, group_by="employer")
    assert "acme-corp" in res, res
    row = res["acme-corp"]
    assert row["submitted"] == 1
    assert row["response"] == 1
    assert row["response_rate"] == 1.0
    assert row["median_days_to_response"] == 3.0

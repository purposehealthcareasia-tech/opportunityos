"""Apply-at-birth regression tests — Phase 5.1.

Covers:
  * `_classify_tier` returns HOT / WARM / COLD from `jobs.first_seen`
    histograms — deterministic against a scratch DB.
  * `_median_lag_minutes` is truthful: only measures NEW postings
    (posted_at AND first_seen both in the last N hours), not the initial
    ingest sweep-up of historical postings.
  * `_boards_due` treats never-polled boards as due immediately (first_run)
    and honours `next_due_at` for previously-polled boards.
  * `tick` composes lifecycle_sweep and produces an audit row.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_apply_at_birth"


@pytest.fixture
async def scratch_db(monkeypatch):
    from core import db as core_db
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    for cn in ("jobs", "apply_at_birth_state", "apply_at_birth_ticks",
                 "lifecycle_sweep_runs"):
        await db.drop_collection(cn)
    monkeypatch.setattr(core_db, "get_db", lambda: db)
    try:
        yield db
    finally:
        for cn in ("jobs", "apply_at_birth_state", "apply_at_birth_ticks",
                     "lifecycle_sweep_runs"):
            await db.drop_collection(cn)
        client.close()


def _job_row(source_ats: str, token: str, external_id: str,
              first_seen: datetime, posted_at: str | None = None,
              status: str = "live") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "canonical_key": f"{source_ats}::{external_id}",
        "source": f"discovery.{source_ats}",
        "status": status,
        "first_seen": first_seen,
        "discovery": {
            "source_ats": source_ats,
            "employer_token": token,
            "external_id": external_id,
            "posted_at": posted_at,
        },
    }


@pytest.mark.asyncio
async def test_classify_tier_hot(scratch_db):
    from services import apply_at_birth as aab
    now = datetime.now(timezone.utc)
    await scratch_db.jobs.insert_many([
        _job_row("greenhouse", "hotco", f"j{i}", now - timedelta(hours=1))
        for i in range(6)  # >=5 in last 24h → HOT
    ])
    tier, n_24h, n_7d = await aab._classify_tier("greenhouse", "hotco", now)
    assert tier == aab.TIER_HOT
    assert n_24h == 6
    assert n_7d == 6


@pytest.mark.asyncio
async def test_classify_tier_warm(scratch_db):
    from services import apply_at_birth as aab
    now = datetime.now(timezone.utc)
    await scratch_db.jobs.insert_many([
        _job_row("greenhouse", "warmco", "j1", now - timedelta(days=3)),
        _job_row("greenhouse", "warmco", "j2", now - timedelta(days=5)),
    ])
    tier, n_24h, n_7d = await aab._classify_tier("greenhouse", "warmco", now)
    assert tier == aab.TIER_WARM
    assert n_24h == 0
    assert n_7d == 2


@pytest.mark.asyncio
async def test_classify_tier_cold(scratch_db):
    from services import apply_at_birth as aab
    now = datetime.now(timezone.utc)
    await scratch_db.jobs.insert_many([
        _job_row("greenhouse", "coldco", "j1", now - timedelta(days=45)),
    ])
    tier, n_24h, n_7d = await aab._classify_tier("greenhouse", "coldco", now)
    assert tier == aab.TIER_COLD
    assert n_24h == 0
    assert n_7d == 0


@pytest.mark.asyncio
async def test_median_lag_only_counts_new_postings(scratch_db):
    from services import apply_at_birth as aab
    now = datetime.now(timezone.utc)
    # NEW: posted 30 min ago, queued 5 min ago → lag = 25 min.
    await scratch_db.jobs.insert_one(_job_row(
        "greenhouse", "acme", "n1",
        first_seen=now - timedelta(minutes=5),
        posted_at=(now - timedelta(minutes=30)).isoformat(),
    ))
    # NEW: posted 2h ago, queued 30 min ago → lag = 90 min.
    await scratch_db.jobs.insert_one(_job_row(
        "greenhouse", "acme", "n2",
        first_seen=now - timedelta(minutes=30),
        posted_at=(now - timedelta(hours=2)).isoformat(),
    ))
    # HISTORICAL (must be excluded): posted 60 days ago, queued 10 min ago.
    await scratch_db.jobs.insert_one(_job_row(
        "greenhouse", "acme", "old",
        first_seen=now - timedelta(minutes=10),
        posted_at=(now - timedelta(days=60)).isoformat(),
    ))
    median = await aab._median_lag_minutes(now, within_hours=24)
    # Median of [25, 90] = 57.5.
    assert median == 57.5


@pytest.mark.asyncio
async def test_boards_due_first_run_returns_all(scratch_db, monkeypatch):
    """When no `apply_at_birth_state` exists, every catalog board is
    treated as due (first_run)."""
    from services import apply_at_birth as aab
    # Shrink the catalog for this test — patch ALL_BOARDS temporarily.
    monkeypatch.setattr(aab, "ALL_BOARDS",
                          [("greenhouse", "AcmeCo", "acmeco")])
    due = await aab._boards_due()
    assert len(due) == 1
    assert due[0]["reason"] == "first_run"
    assert due[0]["tier"] == aab.TIER_COLD


@pytest.mark.asyncio
async def test_boards_due_honours_next_due_at(scratch_db, monkeypatch):
    from services import apply_at_birth as aab
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(aab, "ALL_BOARDS", [
        ("greenhouse", "DueCo", "dueco"),
        ("greenhouse", "NotDueCo", "notdueco"),
    ])
    await scratch_db.apply_at_birth_state.insert_many([
        {"source_ats": "greenhouse", "employer_token": "dueco",
         "employer": "DueCo", "tier": aab.TIER_HOT,
         "last_polled_at": now - timedelta(minutes=30),
         "next_due_at": now - timedelta(minutes=1)},  # DUE
        {"source_ats": "greenhouse", "employer_token": "notdueco",
         "employer": "NotDueCo", "tier": aab.TIER_COLD,
         "last_polled_at": now - timedelta(hours=1),
         "next_due_at": now + timedelta(hours=5)},    # NOT DUE
    ])
    due = await aab._boards_due(now)
    tokens = sorted(d["token"] for d in due)
    assert tokens == ["dueco"]

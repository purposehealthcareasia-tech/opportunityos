"""Surprise Me endpoint — Fynd Liquid directive (2026-07-28).

Locks in the 5/day cap, no-repeat, outside-lane, three-hard-gates
invariants of `POST /api/v1/jobs/surprise-me` + `GET /api/v1/jobs/surprise-me/status`.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_surprise_me"


@pytest.fixture
async def scratch_db(monkeypatch):
    from core import db as core_db
    # `domains/jobs/router.py` uses `from core.db import get_db` at module
    # load, so patch the captured reference directly.
    import domains.jobs.router as jobs_router
    import domains.jobs.repository as jobs_repo
    import services.gate_engine as gate_engine
    # audit.service also captures get_db at import time — patch to avoid
    # a stale motor client from a prior test's event loop.
    import domains.audit.service as audit_svc
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    for cn in ("applications", "jobs", "surprise_me_draws", "audit_logs",
                 "hidden_jobs", "users", "match_scores", "consent_records",
                 "eligibility_profiles", "preferences", "claims"):
        await db.drop_collection(cn)
    monkeypatch.setattr(core_db, "get_db", lambda: db)
    monkeypatch.setattr(jobs_router, "get_db", lambda: db)
    monkeypatch.setattr(audit_svc, "get_db", lambda: db)
    try:
        yield db
    finally:
        for cn in ("applications", "jobs", "surprise_me_draws", "audit_logs",
                     "hidden_jobs", "users", "match_scores", "consent_records"):
            await db.drop_collection(cn)
        client.close()


def _fake_ctx(**overrides):
    """Minimal build_context() shape the pass-all evaluator + scorer need
    to return `pass_all=True` for a stub job. We monkeypatch `evaluate`
    and `score_job` inside the individual tests to make deterministic."""
    base = {"hidden_job_ids": set(), "approved_skills": set()}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_status_endpoint_reports_zero_when_no_draws_today(scratch_db):
    from domains.jobs.router import surprise_me_status
    user_id = f"u-{uuid.uuid4().hex[:6]}"
    result = await surprise_me_status(user={"id": user_id})
    assert result == {"limit": 5, "used_today": 0, "remaining_today": 5}


@pytest.mark.asyncio
async def test_daily_limit_of_five_blocks_sixth_draw(scratch_db):
    from domains.jobs.router import surprise_me
    user_id = f"u-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    for _ in range(5):
        await scratch_db.surprise_me_draws.insert_one({
            "id": str(uuid.uuid4()), "user_id": user_id,
            "job_id": str(uuid.uuid4()), "drawn_at": now,
        })
    with pytest.raises(HTTPException) as excinfo:
        await surprise_me(user={"id": user_id})
    assert excinfo.value.status_code == 429
    assert excinfo.value.detail["error"] == "surprise_daily_limit_reached"
    assert excinfo.value.detail["remaining_today"] == 0


@pytest.mark.asyncio
async def test_sample_jobs_are_never_drawn(scratch_db, monkeypatch):
    from domains.jobs import router as jobs_router
    user_id = f"u-{uuid.uuid4().hex[:6]}"
    # Insert one SAMPLE job that would otherwise pass every gate.
    await scratch_db.jobs.insert_one({
        "id": "sample-1", "status": "live", "is_sample": True,
        "title": "Sample role", "company_name": "SampleCo",
        "taxonomy_family": "eng", "canonical_key": "sampleco::eng-1",
    })
    async def _list_live(): return [
        {"id": "sample-1", "status": "live", "is_sample": True,
         "title": "Sample role", "company_name": "SampleCo",
         "taxonomy_family": "eng", "canonical_key": "sampleco::eng-1"},
    ]
    async def _build_ctx(_): return _fake_ctx()
    def _evaluate(_, __): return {"pass_all": True, "gates": {}, "notes": []}
    def _score(_ctx, _job, _gate): return {"score": 0.9, "reason_codes": []}
    monkeypatch.setattr(jobs_router.jobs_repo, "list_live", _list_live)
    monkeypatch.setattr(jobs_router, "build_context", _build_ctx)
    monkeypatch.setattr(jobs_router, "evaluate", _evaluate)
    monkeypatch.setattr(jobs_router, "score_job", _score)
    result = await jobs_router.surprise_me(user={"id": user_id})
    assert result["job"] is None
    assert result["remaining_today"] == 5
    assert "outside-lane" in result["message"].lower()


@pytest.mark.asyncio
async def test_draw_records_row_and_decrements_remaining(scratch_db, monkeypatch):
    from domains.jobs import router as jobs_router
    user_id = f"u-{uuid.uuid4().hex[:6]}"
    async def _list_live(): return [
        {"id": "real-1", "status": "live", "is_sample": False,
         "title": "Product Designer", "company_name": "acme",
         "taxonomy_family": "design", "canonical_key": "acme::design-1"},
    ]
    async def _build_ctx(_): return _fake_ctx()
    def _evaluate(_, __): return {"pass_all": True, "gates": {}, "notes": []}
    def _score(_ctx, _job, _gate): return {"score": 0.6, "reason_codes": [
        {"weight_applied": 0.2, "explanation": "You have 3 approved design claims."},
    ]}
    monkeypatch.setattr(jobs_router.jobs_repo, "list_live", _list_live)
    monkeypatch.setattr(jobs_router, "build_context", _build_ctx)
    monkeypatch.setattr(jobs_router, "evaluate", _evaluate)
    monkeypatch.setattr(jobs_router, "score_job", _score)
    result = await jobs_router.surprise_me(user={"id": user_id})
    assert result["job"]["id"] == "real-1"
    assert result["remaining_today"] == 4
    assert "You have 3 approved design claims." in result["why_you_qualify"]
    row = await scratch_db.surprise_me_draws.find_one({"user_id": user_id})
    assert row["job_id"] == "real-1"
    assert row["employer"] == "acme"


@pytest.mark.asyncio
async def test_previously_drawn_jobs_are_never_redrawn(scratch_db, monkeypatch):
    from domains.jobs import router as jobs_router
    user_id = f"u-{uuid.uuid4().hex[:6]}"
    # Pre-seed a past draw for the same job.
    await scratch_db.surprise_me_draws.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id, "job_id": "real-1",
        "drawn_at": datetime.now(timezone.utc) - timedelta(days=3),
    })
    async def _list_live(): return [
        {"id": "real-1", "status": "live", "is_sample": False,
         "title": "Product Designer", "company_name": "acme",
         "taxonomy_family": "design", "canonical_key": "acme::design-1"},
    ]
    async def _build_ctx(_): return _fake_ctx()
    def _evaluate(_, __): return {"pass_all": True, "gates": {}, "notes": []}
    def _score(_c, _j, _g): return {"score": 0.6, "reason_codes": []}
    monkeypatch.setattr(jobs_router.jobs_repo, "list_live", _list_live)
    monkeypatch.setattr(jobs_router, "build_context", _build_ctx)
    monkeypatch.setattr(jobs_router, "evaluate", _evaluate)
    monkeypatch.setattr(jobs_router, "score_job", _score)
    result = await jobs_router.surprise_me(user={"id": user_id})
    assert result["job"] is None  # nothing new to draw


@pytest.mark.asyncio
async def test_inside_lane_jobs_are_excluded_when_user_has_apps(scratch_db, monkeypatch):
    from domains.jobs import router as jobs_router
    user_id = f"u-{uuid.uuid4().hex[:6]}"
    # Two existing applications in family "eng" → eng is a "usual" family.
    for _ in range(2):
        await scratch_db.applications.insert_one({
            "id": str(uuid.uuid4()), "user_id": user_id, "state": "shortlisted",
            "job_snapshot": {"taxonomy_family": "eng"},
        })
    async def _list_live(): return [
        # This one would pass but IS inside the usual lane.
        {"id": "eng-1", "status": "live", "is_sample": False,
         "title": "Eng", "company_name": "acme", "taxonomy_family": "eng"},
    ]
    async def _build_ctx(_): return _fake_ctx()
    def _evaluate(_, __): return {"pass_all": True, "gates": {}, "notes": []}
    def _score(_c, _j, _g): return {"score": 0.9, "reason_codes": []}
    monkeypatch.setattr(jobs_router.jobs_repo, "list_live", _list_live)
    monkeypatch.setattr(jobs_router, "build_context", _build_ctx)
    monkeypatch.setattr(jobs_router, "evaluate", _evaluate)
    monkeypatch.setattr(jobs_router, "score_job", _score)
    result = await jobs_router.surprise_me(user={"id": user_id})
    assert result["job"] is None  # inside-lane filtered

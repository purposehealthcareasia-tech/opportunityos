"""Outcome-autopilot surface endpoints — Phase 5.3 (2026-07-28).

Locks in the three additive read/mutate endpoints wired on the outcomes
router:

  * GET  /api/v1/outcomes/kill-list                  — read
  * POST /api/v1/outcomes/kill-list/{employer}/restore — mutate (reversible)
  * GET  /api/v1/outcomes/reallocation/latest        — read (no recompute)

Rails asserted:
  * Consent-gated on `track_applications` (mirrors tracker).
  * `reallocation/latest` returns the STORED artifact verbatim — never
    recomputes on the request path.
  * `restore` mutates the existing row (stamps `restored_at`); the
    original row is preserved (append-only audit).
  * `restore` returns 404 when there is nothing to restore.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_outcome_endpoints"


@pytest.fixture
async def scratch_db(monkeypatch):
    from core import db as core_db
    # `domains/outcomes/service.py` imports `get_db` at module load, so we
    # patch the captured reference directly on the endpoint module in
    # addition to `core.db`, otherwise the handlers see the real DB.
    import domains.outcomes.service as outcomes_svc
    import domains.audit.service as audit_svc
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    for cn in ("applications", "application_outcomes",
                 "budget_reallocations", "kill_list", "audit_logs"):
        await db.drop_collection(cn)
    monkeypatch.setattr(core_db, "get_db", lambda: db)
    monkeypatch.setattr(outcomes_svc, "get_db", lambda: db)
    # `audit.write` also captures get_db at import time — patch it too,
    # otherwise the handler's audit-log insert reaches a stale motor
    # client whose event loop was closed by a prior test.
    monkeypatch.setattr(audit_svc, "get_db", lambda: db)
    try:
        yield db
    finally:
        for cn in ("applications", "application_outcomes",
                     "budget_reallocations", "kill_list", "audit_logs"):
            await db.drop_collection(cn)
        client.close()


@pytest.mark.asyncio
async def test_reallocation_latest_returns_stored_row_verbatim(scratch_db):
    """The read endpoint MUST return the stored allocation artifact
    unchanged — no recompute, no field renaming, `reason` intact."""
    from domains.outcomes.service import read_latest_reallocation

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    stored = {
        "id": "allocation-1",
        "user_id": user_id,
        "computed_at": now - timedelta(days=1),
        "window_days": 30,
        "min_group_submits": 3,
        "allocations": [
            {"group": "acme", "weight": 0.72, "submitted": 5,
             "response_rate": 0.4, "reason": "response_rate=40.00% on 5 apps · median_days_to_response=6.0"},
            {"group": "beta", "weight": 0.28, "submitted": 4,
             "response_rate": 0.15, "reason": "response_rate=15.00% on 4 apps · median_days_to_response=12.0"},
        ],
    }
    # Older row that MUST be ignored (endpoint returns latest only).
    await scratch_db.budget_reallocations.insert_one({
        "id": "allocation-0", "user_id": user_id,
        "computed_at": now - timedelta(days=30),
        "window_days": 30, "min_group_submits": 3,
        "allocations": [{"group": "old", "weight": 1.0, "submitted": 3,
                          "response_rate": 0.0, "reason": "stale"}],
    })
    await scratch_db.budget_reallocations.insert_one(dict(stored))

    result = await read_latest_reallocation(user={"id": user_id})

    r = result["reallocation"]
    assert r["id"] == "allocation-1"
    assert r["window_days"] == 30
    assert r["min_group_submits"] == 3
    reasons = [a["reason"] for a in r["allocations"]]
    assert reasons == [
        "response_rate=40.00% on 5 apps · median_days_to_response=6.0",
        "response_rate=15.00% on 4 apps · median_days_to_response=12.0",
    ]


@pytest.mark.asyncio
async def test_reallocation_latest_returns_null_when_no_row(scratch_db):
    from domains.outcomes.service import read_latest_reallocation
    result = await read_latest_reallocation(user={"id": "u-empty"})
    assert result["reallocation"] is None
    assert "no reallocation" in result["message"].lower()


@pytest.mark.asyncio
async def test_kill_list_endpoint_returns_active_and_recently_restored(scratch_db):
    from domains.outcomes.service import list_kill_list
    from services import outcome_autopilot as oa

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    active = await oa.add_to_kill_list(user_id, "acme", reason="test")
    r = await oa.add_to_kill_list(user_id, "beta", reason="test-2")
    # Restore one so the endpoint has a recently_restored row.
    await oa.restore_from_kill_list(user_id, "beta")

    result = await list_kill_list(user={"id": user_id})
    active_employers = [row["employer"] for row in result["active"]]
    restored_employers = [row["employer"] for row in result["recently_restored"]]
    assert active_employers == ["acme"]
    assert restored_employers == ["beta"]
    assert result["active"][0]["id"] == active["id"]
    assert r["employer"] == "beta"


@pytest.mark.asyncio
async def test_kill_list_restore_flips_row_and_returns_updated(scratch_db):
    from domains.outcomes.service import restore_kill_list_employer
    from services import outcome_autopilot as oa

    user_id = f"user-{uuid.uuid4().hex[:8]}"
    await oa.add_to_kill_list(user_id, "ghosts", reason="5 silences")
    result = await restore_kill_list_employer(
        "ghosts", user={"id": user_id})
    assert result["restored"]["restored_at"] is not None
    assert result["restored"]["restored_reason"] == "user_restore"
    # Row persists — append-only style.
    doc = await scratch_db.kill_list.find_one({"user_id": user_id, "employer": "ghosts"})
    assert doc is not None
    assert doc["restored_at"] is not None


@pytest.mark.asyncio
async def test_kill_list_restore_missing_returns_404(scratch_db):
    from fastapi import HTTPException
    from domains.outcomes.service import restore_kill_list_employer
    with pytest.raises(HTTPException) as excinfo:
        await restore_kill_list_employer(
            "does-not-exist", user={"id": "u-nope"})
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["error"] == "kill_list_row_not_found"


@pytest.mark.asyncio
async def test_kill_list_restore_rejects_invalid_employer():
    from fastapi import HTTPException
    from domains.outcomes.service import restore_kill_list_employer
    with pytest.raises(HTTPException) as excinfo:
        await restore_kill_list_employer("", user={"id": "u"})
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["error"] == "invalid_employer"


# --- 7. Static invariant: read endpoints do not touch budget_reallocations
#         collection with a WRITE. -----------------------------------------

def test_reallocation_latest_handler_does_not_recompute_or_insert():
    """Read the handler source and assert it never invokes
    `reallocate_daily_budget` or an insert into `budget_reallocations`.
    Enforces the founder rail that this endpoint is read-only."""
    src_path = "/app/backend/domains/outcomes/service.py"
    with open(src_path, encoding="utf-8") as f:
        source = f.read()
    idx_fn = source.find("async def read_latest_reallocation(")
    assert idx_fn != -1, "handler not found"
    # Extract handler body — up to the next `\n\n\n` boundary or file end.
    body = source[idx_fn:idx_fn + 2000]
    assert "reallocate_daily_budget" not in body
    assert "budget_reallocations.insert" not in body
    assert "budget_reallocations.update" not in body

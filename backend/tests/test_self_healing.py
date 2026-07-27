"""Self-healing regression tests — Phase 5.4."""
from __future__ import annotations

import os
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_self_healing"


@pytest.fixture
async def scratch_db(monkeypatch):
    from core import db as core_db
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    for cn in ("form_maps", "applications", "self_healing_events"):
        await db.drop_collection(cn)
    monkeypatch.setattr(core_db, "get_db", lambda: db)
    try:
        yield db
    finally:
        for cn in ("form_maps", "applications", "self_healing_events"):
            await db.drop_collection(cn)
        client.close()


def test_threshold_check_returns_false_for_missing_map():
    from services import self_healing as sh
    assert sh.threshold_check(None) is False


def test_threshold_check_respects_status_and_confidence():
    from services import self_healing as sh
    from services import form_map_cache as fmc
    ok = {"status": fmc.STATUS_VERIFIED, "fill_confidence": 0.8}
    bad_status = {"status": fmc.STATUS_DEMOTED, "fill_confidence": 0.9}
    bad_conf = {"status": fmc.STATUS_VERIFIED, "fill_confidence": 0.5}
    assert sh.threshold_check(ok, threshold=0.7) is True
    assert sh.threshold_check(bad_status, threshold=0.7) is False
    assert sh.threshold_check(bad_conf, threshold=0.7) is False


@pytest.mark.asyncio
async def test_downgrade_map_calls_form_map_demote_and_audits(scratch_db):
    from services import self_healing as sh
    from services import form_map_cache as fmc
    fields = [{"name": "email", "type": "email", "required": True}]
    r = await fmc.record_verified(
        ats="greenhouse", url="https://x/y",
        fields=fields, verified_by_source="test:1",
        filled_count=1, found_count=1,
    )
    fp = r["fingerprint"]
    await sh.downgrade_map_to_assisted(
        ats="greenhouse", fingerprint=fp,
        reason="fill_confidence_below_threshold",
        source="test",
    )
    row = await scratch_db.form_maps.find_one(
        {"ats": "greenhouse", "fingerprint": fp}, {"_id": 0})
    assert row["status"] == fmc.STATUS_DEMOTED
    assert row["fill_confidence"] == 0.0
    ev = await scratch_db.self_healing_events.find_one(
        {"context.fingerprint": fp}, {"_id": 0})
    assert ev is not None
    assert ev["kind"] == sh.EVENT_MAP_DEMOTED_LOW_CONFIDENCE


@pytest.mark.asyncio
async def test_downgrade_map_fingerprint_drift_uses_drift_event_kind(scratch_db):
    from services import self_healing as sh
    from services import form_map_cache as fmc
    fields = [{"name": "email", "type": "email", "required": True}]
    r = await fmc.record_verified(
        ats="lever", url="https://x/y",
        fields=fields, verified_by_source="test:1",
        filled_count=1, found_count=1,
    )
    await sh.downgrade_map_to_assisted(
        ats="lever", fingerprint=r["fingerprint"],
        reason="fingerprint_drift_detected_after_source_update",
        source="test",
    )
    ev = await scratch_db.self_healing_events.find_one(
        {"context.fingerprint": r["fingerprint"]}, {"_id": 0})
    assert ev["kind"] == sh.EVENT_MAP_DEMOTED_FINGERPRINT_DRIFT


@pytest.mark.asyncio
async def test_route_application_to_assisted_sets_state_and_reason(scratch_db):
    from services import self_healing as sh
    app_id = f"app-{uuid.uuid4().hex[:8]}"
    user_id = f"user-{uuid.uuid4().hex[:8]}"
    await scratch_db.applications.insert_one({
        "id": app_id, "user_id": user_id, "state": "shortlisted",
    })
    await sh.route_application_to_assisted(
        application_id=app_id, user_id=user_id,
        reason="fill_confidence_below_0.7", source="test",
    )
    app = await scratch_db.applications.find_one(
        {"id": app_id}, {"_id": 0, "state": 1, "assisted_reason": 1})
    assert app["state"] == "assisted"
    assert app["assisted_reason"] == "fill_confidence_below_0.7"

    reason = await sh.assisted_lane_reason(app_id)
    assert reason is not None
    assert reason["reason"] == "fill_confidence_below_0.7"


@pytest.mark.asyncio
async def test_assisted_lane_reason_none_for_non_assisted_app(scratch_db):
    from services import self_healing as sh
    app_id = f"app-{uuid.uuid4().hex[:8]}"
    await scratch_db.applications.insert_one({
        "id": app_id, "user_id": "u", "state": "shortlisted",
    })
    assert await sh.assisted_lane_reason(app_id) is None


@pytest.mark.asyncio
async def test_log_silent_and_wrong_submission_are_audited(scratch_db):
    from services import self_healing as sh
    await sh.log_silent_failure(source="test", context={"note": "x"})
    await sh.log_wrong_submission(source="test",
                                     context={"note": "y", "app_id": "a"})
    kinds = set()
    async for ev in scratch_db.self_healing_events.find({}, {"_id": 0, "kind": 1}):
        kinds.add(ev["kind"])
    assert sh.EVENT_SILENT_FAILURE in kinds
    assert sh.EVENT_WRONG_SUBMISSION in kinds

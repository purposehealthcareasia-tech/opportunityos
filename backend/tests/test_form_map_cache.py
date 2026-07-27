"""Form-map cache regression tests — Phase 5.2."""
from __future__ import annotations

import json
import os
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_form_map_cache"


@pytest.fixture
async def scratch_db(monkeypatch):
    from core import db as core_db
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    await db.drop_collection("form_maps")
    monkeypatch.setattr(core_db, "get_db", lambda: db)
    try:
        yield db
    finally:
        await db.drop_collection("form_maps")
        client.close()


def test_canonical_fingerprint_is_stable_across_reordering():
    from services import form_map_cache as fmc
    a = fmc.canonical_fingerprint([
        {"name": "first_name", "type": "text", "required": True},
        {"name": "email", "type": "email", "required": True},
    ])
    b = fmc.canonical_fingerprint([
        {"name": "email", "type": "email", "required": True},
        {"name": "first_name", "type": "text", "required": True},
    ])
    assert a == b
    # But adding a new required field changes the fingerprint.
    c = fmc.canonical_fingerprint([
        {"name": "first_name", "type": "text", "required": True},
        {"name": "email", "type": "email", "required": True},
        {"name": "phone", "type": "tel", "required": True},
    ])
    assert c != a


def test_url_fingerprint_ignores_query_string():
    from services import form_map_cache as fmc
    a = fmc.url_fingerprint("https://boards.greenhouse.io/acme/jobs/123")
    b = fmc.url_fingerprint("https://boards.greenhouse.io/acme/jobs/123?gh_jid=999")
    c = fmc.url_fingerprint("https://boards.greenhouse.io/acme/jobs/123#app")
    assert a == b == c


@pytest.mark.asyncio
async def test_record_verified_upserts_and_bumps_confidence(scratch_db):
    from services import form_map_cache as fmc
    fields = [
        {"name": "first_name", "type": "text", "required": True},
        {"name": "email", "type": "email", "required": True},
    ]
    r1 = await fmc.record_verified(
        ats="greenhouse", url="https://x/y",
        fields=fields, verified_by_source="test:1", filled_count=4, found_count=8,
    )
    assert r1["verified_by_count"] == 1
    assert r1["status"] == fmc.STATUS_VERIFIED
    assert r1["structure_captured"] is True

    r2 = await fmc.record_verified(
        ats="greenhouse", url="https://x/y",
        fields=fields, verified_by_source="test:2", filled_count=4, found_count=8,
    )
    assert r2["verified_by_count"] == 2
    assert r2["fill_confidence"] >= r1["fill_confidence"]

    # One row per (ats, fingerprint) — upsert path is exercised.
    assert await scratch_db.form_maps.count_documents({}) == 1


@pytest.mark.asyncio
async def test_lookup_returns_none_when_missing(scratch_db):
    from services import form_map_cache as fmc
    assert await fmc.lookup("greenhouse", "sha256:nonexistent") is None


@pytest.mark.asyncio
async def test_demote_marks_status_and_zeroes_confidence(scratch_db):
    from services import form_map_cache as fmc
    fields = [{"name": "email", "type": "email", "required": True}]
    r = await fmc.record_verified(
        ats="lever", url="https://jobs.lever.co/x/y/apply",
        fields=fields, verified_by_source="test:1", filled_count=1, found_count=1,
    )
    d = await fmc.demote("lever", r["fingerprint"], reason="fingerprint_drift")
    assert d is not None
    assert d["status"] == fmc.STATUS_DEMOTED
    assert d["fill_confidence"] == 0.0
    assert d["demote_reason"] == "fingerprint_drift"
    assert len(d["demote_events"]) == 1
    assert d["demote_events"][0]["reason"] == "fingerprint_drift"


@pytest.mark.asyncio
async def test_url_bootstrap_uses_url_fingerprint_and_marks_structure_not_captured(scratch_db):
    from services import form_map_cache as fmc
    r = await fmc.record_verified(
        ats="greenhouse", url="https://boards.greenhouse.io/acme/jobs/1",
        fields=None, verified_by_source="dryrun:1",
        filled_count=6, found_count=25,
    )
    assert r["structure_captured"] is False
    assert r["fingerprint"].startswith("url:")


@pytest.mark.asyncio
async def test_selector_map_sanitizes_input(scratch_db):
    from services import form_map_cache as fmc
    # Simulate a caller trying to smuggle user data via selector_map.
    r = await fmc.record_verified(
        ats="greenhouse", url="https://x/y",
        fields=[{"name": "email", "type": "email", "required": True}],
        selector_map=[
            {"selector": "input[name=email]", "role": "email",
             "confidence": 0.9,
             # These fields are IGNORED — never leaked into storage.
             "value": "user@leak.com",
             "phone": "+1-555-0001"},
        ],
        verified_by_source="test:1", filled_count=1, found_count=1,
    )
    assert len(r["selector_map"]) == 1
    sm = r["selector_map"][0]
    # Only whitelisted keys are stored.
    assert set(sm.keys()) == {"selector", "role", "confidence"}
    assert sm["selector"] == "input[name=email]"


@pytest.mark.asyncio
async def test_bootstrap_from_dryrun_json_records_only_successful_urls(scratch_db, tmp_path):
    from services import form_map_cache as fmc
    audit = {
        "started_at": "2026-07-27T22:08:37+00:00",
        "results": [
            {"index": 0, "url": "https://boards.greenhouse.io/x/jobs/1",
             "state": "filled_and_aborted", "fields_filled_correctly": True,
             "fields_found": 25, "fields_filled": 6},
            {"index": 1, "url": "https://jobs.lever.co/y/uuid/apply",
             "state": "filled_and_aborted", "fields_filled_correctly": True,
             "fields_found": 22, "fields_filled": 5},
            # SKIPPED — CAPTCHA
            {"index": 2, "url": "https://boards.greenhouse.io/z/jobs/2",
             "state": "skipped_captcha", "fields_filled_correctly": False},
            # SKIPPED — filled but not correct
            {"index": 3, "url": "https://boards.greenhouse.io/w/jobs/3",
             "state": "filled_and_aborted", "fields_filled_correctly": False,
             "fields_found": 25, "fields_filled": 2},
        ],
    }
    p = tmp_path / "dryrun.json"
    p.write_text(json.dumps(audit))
    summary = await fmc.bootstrap_from_dryrun_json(str(p),
                                                     source_tag_prefix="test_dryrun")
    assert summary["recorded"] == 2
    assert summary["skipped"] == 2
    assert await scratch_db.form_maps.count_documents({}) == 2
    # Both bootstrap entries must be URL-fingerprint (structure_captured=False).
    async for row in scratch_db.form_maps.find({}, {"_id": 0}):
        assert row["structure_captured"] is False
        assert row["fingerprint"].startswith("url:")
        assert row["status"] == fmc.STATUS_VERIFIED
        assert row["verified_by_sources"][0].startswith("test_dryrun_")

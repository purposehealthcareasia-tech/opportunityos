"""Mongo unique-index proofs (Founder Directive #4).

Uses a scratch DB `oppos_test_p3` so we never touch the running seed.
"""
from __future__ import annotations
import os
import uuid
import pytest
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "oppos_test_p3"

OPEN_STATES = ["shortlisted", "preparing", "awaiting_approval", "approved",
               "submitting", "submitted", "response", "interview", "offer"]


@pytest.fixture
async def db():
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    for coll in ("jobs", "submission_receipts", "usage_meters", "applications"):
        await db.drop_collection(coll)
    await db.jobs.create_index("canonical_key", unique=True)
    await db.submission_receipts.create_index(
        [("user_id", ASCENDING), ("company_id", ASCENDING), ("req_ref", ASCENDING)],
        unique=True,
    )
    await db.usage_meters.create_index([("user_id", ASCENDING), ("period", ASCENDING)], unique=True)
    await db.applications.create_index(
        [("user_id", ASCENDING), ("job_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"state": {"$in": OPEN_STATES}},
        name="uniq_open_app_per_user_job",
    )
    try:
        yield db
    finally:
        client.close()


@pytest.mark.asyncio
async def test_unique_canonical_key_blocks_duplicate_ingest(db):
    key = f"foo.com::{uuid.uuid4().hex}"
    await db.jobs.insert_one({"canonical_key": key, "title": "A"})
    with pytest.raises(Exception) as exc:
        await db.jobs.insert_one({"canonical_key": key, "title": "B"})
    assert "duplicate" in str(exc.value).lower() or "E11000" in str(exc.value)


@pytest.mark.asyncio
async def test_unique_submission_receipt_blocks_duplicate(db):
    row = {
        "user_id": "u1", "company_id": "c1", "req_ref": "REF-X",
        "application_id": "a1", "job_id": "j1",
        "materials_manifest_hash": "h", "submit_channel": "email",
        "ts": datetime.now(timezone.utc),
    }
    await db.submission_receipts.insert_one(row.copy())
    with pytest.raises(Exception) as exc:
        r2 = row.copy(); r2.pop("_id", None)
        await db.submission_receipts.insert_one(r2)
    assert "duplicate" in str(exc.value).lower() or "E11000" in str(exc.value)


@pytest.mark.asyncio
async def test_unique_usage_meter_per_period(db):
    row = {"user_id": "u1", "period": "2026-02", "jobs_processed": 0}
    await db.usage_meters.insert_one(row.copy())
    with pytest.raises(Exception) as exc:
        r2 = row.copy(); r2.pop("_id", None)
        await db.usage_meters.insert_one(r2)
    assert "duplicate" in str(exc.value).lower() or "E11000" in str(exc.value)


@pytest.mark.asyncio
async def test_unique_open_application_partial_index_allows_closed(db):
    """Two OPEN apps for same (user, job) rejected; a CLOSED one alongside an OPEN one is allowed."""
    await db.applications.insert_one({
        "user_id": "u1", "job_id": "j1", "state": "shortlisted",
    })
    with pytest.raises(Exception) as exc:
        await db.applications.insert_one({
            "user_id": "u1", "job_id": "j1", "state": "shortlisted",
        })
    assert "duplicate" in str(exc.value).lower() or "E11000" in str(exc.value)
    # CLOSED alongside OPEN is fine (partial index excludes closed)
    await db.applications.insert_one({
        "user_id": "u1", "job_id": "j1", "state": "closed",
    })
    assert await db.applications.count_documents({"user_id": "u1", "job_id": "j1"}) == 2

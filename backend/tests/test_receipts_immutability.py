"""Phase 5 receipt immutability — proves the app can't mutate a receipt or bypass
the (user, company, req_ref) unique index."""
from __future__ import annotations
import asyncio
import inspect
import os
import uuid

import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

# Direct sync client (mirrors the sync pymongo pattern used elsewhere in the tests).
def _read_env(path: str, key: str) -> str:
    try:
        for line in open(path):
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get(key, "")


MONGO_URL = _read_env("/app/backend/.env", "MONGO_URL")
DB_NAME = _read_env("/app/backend/.env", "DB_NAME")


def _sync_db():
    return MongoClient(MONGO_URL, uuidRepresentation="standard")[DB_NAME]


def test_receipt_module_exposes_no_mutation_functions():
    """There must be NO update/delete/upsert/patch callable on the receipts module. Ever."""
    from domains.submission_receipts import service as receipts
    coroutines = {name for name, obj in inspect.getmembers(receipts) if inspect.iscoroutinefunction(obj)}
    all_public = {name for name in dir(receipts) if not name.startswith("_")}
    forbidden_words = ("update", "delete", "remove", "upsert", "patch", "mutate")
    hits = {n for n in all_public if any(w in n.lower() for w in forbidden_words)}
    assert not hits, f"receipts module exposes forbidden mutators: {hits}"
    # Also assert no HTTP router surface exposes a mutation. The domain has NO APIRouter export.
    assert not hasattr(receipts, "router"), "receipts.service must not export an HTTP router"


def test_duplicate_receipt_raises_by_unique_index():
    """Two inserts with identical (user, company, req_ref) must fail at Mongo layer."""
    db = _sync_db()
    key = f"immut-{uuid.uuid4().hex[:8]}"
    # First insert
    db.submission_receipts.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": key, "company_id": "acme.com", "req_ref": "req-immut-1",
        "application_id": "app-1", "job_id": "job-1",
        "materials_manifest_hash": "h1", "submit_channel": "guided_manual",
        "supersedes": None,
    })
    # Second insert with same (user, company, req_ref) — Mongo unique index MUST reject.
    with pytest.raises(DuplicateKeyError):
        db.submission_receipts.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": key, "company_id": "acme.com", "req_ref": "req-immut-1",
            "application_id": "app-1", "job_id": "job-1",
            "materials_manifest_hash": "h2", "submit_channel": "guided_manual",
            "supersedes": None,
        })
    # Cleanup
    db.submission_receipts.delete_many({"user_id": key})


def test_supersedes_chain_keeps_original_row():
    """A correction is a NEW row pointing at the original — original stays put."""
    db = _sync_db()
    key = f"chain-{uuid.uuid4().hex[:8]}"
    r1_id = str(uuid.uuid4())
    r2_id = str(uuid.uuid4())
    db.submission_receipts.insert_one({
        "id": r1_id, "user_id": key, "company_id": "acme.com", "req_ref": f"req-chain-a-{key}",
        "application_id": "app-1", "job_id": "job-1",
        "materials_manifest_hash": "v1", "submit_channel": "guided_manual",
        "supersedes": None,
    })
    db.submission_receipts.insert_one({
        "id": r2_id, "user_id": key, "company_id": "acme.com", "req_ref": f"req-chain-b-{key}",
        "application_id": "app-1", "job_id": "job-1",
        "materials_manifest_hash": "v2", "submit_channel": "guided_manual",
        "supersedes": r1_id,
    })
    # Original row still present.
    original = db.submission_receipts.find_one({"id": r1_id})
    assert original is not None, "original receipt must NOT be removed by a correction"
    # P2a.2: reset core.db._client / _db so `find_effective`'s asyncio.run
    # creates a fresh Motor client inside its own event loop. Otherwise
    # a cached Motor client bound to a previously-closed loop raises
    # `RuntimeError: Event loop is closed`.
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    # Application-layer helper picks the latest non-superseded row.
    from domains.submission_receipts import service as receipts
    effective = asyncio.run(receipts.find_effective(user_id=key, application_id="app-1"))
    assert effective is not None
    assert effective["id"] == r2_id
    # Cleanup
    db.submission_receipts.delete_many({"user_id": key})

"""Deployment readiness — PROD_MODE seed guard regression.

Locks in the 2026-02-21 deployment-blocker fix:

  - `run_seeds()` MUST NOT create hardcoded-password admin/support/fixture
    accounts or seed SampleCo demo data when `PROD_MODE=true`.
  - The `/api/internal/fixture/rebase` endpoint MUST return 503 in prod mode.
  - Reference data (taxonomy + feature flags) MUST still seed in prod so the
    role-family taxonomy and feature-flag registry are usable on day one.

Isolation strategy — to avoid pytest-asyncio event-loop cross-contamination
that broke `test_milestone_e_google` when we naively created a Motor client
in a fixture, each async test creates its OWN Motor client inside the test
function's event loop and closes it before yielding. Teardown uses
`pymongo` (sync) so the drop never touches an already-closed loop.
"""
from __future__ import annotations

import uuid

import pytest
import pymongo
from motor.motor_asyncio import AsyncIOMotorClient

from core import db as db_module
from core.config import settings
from domains.seeds import seeder
from domains.subscriptions import service as subs_svc


def _sync_drop(dbname: str) -> None:
    try:
        pymongo.MongoClient(settings.MONGO_URL).drop_database(dbname)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_prod_mode_seed_skips_fixture_accounts(monkeypatch):
    """Assert PROD_MODE=true seeds only reference data and NO fixture accounts."""
    dbname = f"opportunityos_deploy_test_{uuid.uuid4().hex[:8]}"
    client = AsyncIOMotorClient(settings.MONGO_URL, uuidRepresentation="standard")
    try:
        fake_db = client[dbname]
        monkeypatch.setattr(db_module, "get_db", lambda: fake_db)
        monkeypatch.setattr(seeder, "get_db", lambda: fake_db)
        monkeypatch.setattr(subs_svc, "get_db", lambda: fake_db)
        monkeypatch.setattr(settings, "PROD_MODE", True)

        counts = await seeder.run_seeds()

        # Reference data still lands.
        assert counts["taxonomy"] > 0
        assert counts["feature_flags"] > 0
        # Sensitive seed operations are skipped.
        assert counts["prod_mode_seed_skipped"] is True
        assert counts["sample_jobs"] == 0
        assert counts["companies"] == 0
        assert counts["fixture_user_id"] is None
        assert counts["user_zero_id"] is None
        assert counts["admin_users"] == 0

        # Verify at the collection level — no hardcoded-password accounts inserted.
        forbidden_emails = [
            "admin@opportunityos.dev",
            "support@opportunityos.dev",
            "ujjwal@opportunityos.dev",
            "fixture-ead@opportunityos.dev",
        ]
        for email in forbidden_emails:
            assert await fake_db.users.find_one({"email": email}) is None, (
                f"PROD_MODE seed leaked hardcoded-password account: {email}"
            )
        # No SampleCo demo jobs / company either.
        assert await fake_db.jobs.count_documents({}) == 0
        assert await fake_db.companies.find_one({"domain": "sampleco.demo"}) is None
        # But taxonomy + feature_flags are usable.
        assert await fake_db.taxonomy.count_documents({}) > 0
        assert await fake_db.feature_flags.count_documents({}) > 0
    finally:
        client.close()
        _sync_drop(dbname)


@pytest.mark.asyncio
async def test_preview_mode_seed_creates_full_fixture(monkeypatch):
    """Baseline: PROD_MODE=false (preview / dev) MUST still seed the full fixture."""
    dbname = f"opportunityos_deploy_test_{uuid.uuid4().hex[:8]}"
    client = AsyncIOMotorClient(settings.MONGO_URL, uuidRepresentation="standard")
    try:
        fake_db = client[dbname]
        monkeypatch.setattr(db_module, "get_db", lambda: fake_db)
        monkeypatch.setattr(seeder, "get_db", lambda: fake_db)
        monkeypatch.setattr(subs_svc, "get_db", lambda: fake_db)
        monkeypatch.setattr(settings, "PROD_MODE", False)

        counts = await seeder.run_seeds()

        assert counts["taxonomy"] > 0
        assert counts["feature_flags"] > 0
        # SampleCo geometry is derived from seed data; imports keep this in
        # sync with any future addition/removal in SAMPLE_JOBS.
        from tests._fixture_expectations import SAMPLE_JOB_TOTAL
        from domains.seeds import data as _seed_data
        assert counts["sample_jobs"] == len(_seed_data.SAMPLE_JOBS)
        assert counts["fixture_user_id"] is not None
        assert counts["user_zero_id"] is not None
        assert counts["admin_users"] == 2
        assert "prod_mode_seed_skipped" not in counts

        # Fixture accounts exist.
        for email in [
            "admin@opportunityos.dev",
            "support@opportunityos.dev",
            "ujjwal@opportunityos.dev",
            "fixture-ead@opportunityos.dev",
        ]:
            assert await fake_db.users.find_one({"email": email}) is not None
    finally:
        client.close()
        _sync_drop(dbname)


@pytest.mark.asyncio
async def test_fixture_rebase_endpoint_disabled_in_prod_mode(monkeypatch):
    """The `/api/internal/fixture/rebase` route handler MUST refuse in prod mode.

    Directly invokes the async route handler — no TestClient, no FastAPI app
    instantiation — so we don't create a competing event loop.
    """
    from fastapi import HTTPException
    from domains.fixtures import internal_router as fixture_mod

    monkeypatch.setattr(settings, "PROD_MODE", True)

    with pytest.raises(HTTPException) as excinfo:
        await fixture_mod.rebase_fixture()

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["error"] == "fixture_rebase_disabled_in_prod"

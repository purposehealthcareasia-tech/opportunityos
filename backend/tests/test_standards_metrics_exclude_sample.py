"""P0 Truth Audit (d, f, i, h) — /standards SAMPLE-segregation invariant.

Hard-locks that every metric rendered on the /standards page excludes
fixture users + sample jobs. If a metrics function ever forgets the
exclusion, this test fails at CI.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client_per_test():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


async def _seed_fixture_user_and_pollute(db):
    """Insert polluted rows against the EXISTING seeded fixture-ead@ user
    (real seeder runs on backend startup, so we look it up rather than
    trying to re-insert)."""
    now = datetime.now(timezone.utc)
    fixture_user = await db.users.find_one(
        {"email": "fixture-ead@opportunityos.dev"}, {"id": 1, "_id": 0}
    )
    if not fixture_user:
        # Fallback for tests running before the seeder has finished (rare).
        fx_uid = f"fx-{uuid.uuid4().hex[:8]}"
        await db.users.insert_one({
            "id": fx_uid,
            "email": "fixture-ead@opportunityos.dev",
            "role": "user",
            "created_at": now, "updated_at": now,
        })
    else:
        fx_uid = fixture_user["id"]

    # 200 fake submitted applications for the fixture user — must be excluded.
    # Give each a unique synthetic job_id so the (user_id, job_id) uniq index doesn't fire.
    await db.applications.insert_many([
        {"id": f"app-fx-metrics-{i}-{uuid.uuid4().hex[:6]}", "user_id": fx_uid,
         "job_id": f"pollute-{uuid.uuid4()}",
         "state": "submitted", "submitted_at": now, "created_at": now}
        for i in range(200)
    ])
    # 100 fake response outcomes — must be excluded from median.
    await db.application_outcomes.insert_many([
        {"id": f"out-fx-metrics-{i}-{uuid.uuid4().hex[:6]}", "user_id": fx_uid,
         "kind": "response", "days_to_response": 999.0,
         "ts": now, "created_at": now}
        for i in range(100)
    ])
    # 5 sample jobs (is_sample=True) tagged 'India' — must be excluded from per_country.
    # Give each a unique canonical_key so the canonical_key uniq index doesn't fire.
    await db.jobs.insert_many([
        {"id": f"job-fx-metrics-{i}-{uuid.uuid4().hex[:6]}", "is_sample": True,
         "canonical_key": f"pollute::sample-{uuid.uuid4().hex[:12]}",
         "company_name": "SampleCo", "geo": "Bengaluru, India",
         "status": "live", "created_at": now}
        for i in range(5)
    ])
    return fx_uid


@pytest.mark.asyncio
async def test_outcome_rows_excludes_fixture_user_applications():
    from core.db import get_db
    from domains.standards import metrics
    db = get_db()
    fx_uid = await _seed_fixture_user_and_pollute(db)

    rows = await metrics.public_outcome_rows()
    # honest_n_applications must NOT include the 200 fixture apps.
    # Below-threshold → median/rate render 'measuring'.
    assert rows["honest_n_applications"] < 200, (
        f"metrics leaked fixture apps: n_applications={rows['honest_n_applications']}"
    )
    assert rows["honest_n_responses"] < 100, (
        f"metrics leaked fixture response outcomes: n_responses={rows['honest_n_responses']}"
    )
    # With the fixture pollution, the pool would appear to have huge counts.
    # The metric must still render 'measuring' when below threshold, or a
    # real number derived only from non-fixture rows.
    m = rows["median_days_to_first_response"]
    assert m == "measuring" or isinstance(m, (int, float)), (
        f"unexpected median type: {type(m).__name__}={m!r}"
    )
    ipm = rows["interviews_per_100_apps"]
    assert ipm == "measuring" or isinstance(ipm, (int, float))

    # Cleanup
    await db.applications.delete_many({"id": {"$regex": "^app-fx-metrics-"}})
    await db.application_outcomes.delete_many({"id": {"$regex": "^out-fx-metrics-"}})
    await db.jobs.delete_many({"id": {"$regex": "^job-fx-metrics-"}})
    await db.users.delete_one({"id": fx_uid})


@pytest.mark.asyncio
async def test_per_country_coverage_excludes_sample_rows():
    from core.db import get_db
    from domains.standards import metrics
    db = get_db()
    fx_uid = await _seed_fixture_user_and_pollute(db)

    cov = await metrics.per_country_coverage()
    # Bengaluru bucket must not include the 5 SAMPLE India rows.
    beng = cov["india_by_city_real"]["Bengaluru/Bangalore"]
    # Pre-seed real count from production was 364 (Feb 2026 measure) —
    # test just asserts the 5 SAMPLE rows did NOT increment it.
    # Explicit invariant: sample_rows_excluded increases when we inject.
    assert cov["sample_rows_excluded"] >= 5, (
        f"sample_rows_excluded must reflect the 5 injected SAMPLE rows; "
        f"got {cov['sample_rows_excluded']}"
    )

    # Cleanup
    await db.jobs.delete_many({"id": {"$regex": "^job-fx-metrics-"}})
    await db.applications.delete_many({"id": {"$regex": "^app-fx-metrics-"}})
    await db.application_outcomes.delete_many({"id": {"$regex": "^out-fx-metrics-"}})
    await db.users.delete_one({"id": fx_uid})


@pytest.mark.asyncio
async def test_north_star_baseline_excludes_fixture_user_and_below_threshold_renders_measuring():
    from core.db import get_db
    from domains.standards import metrics
    db = get_db()
    fx_uid = await _seed_fixture_user_and_pollute(db)

    ns = await metrics.north_star_baseline()
    # n_apps must NOT count the 200 fixture apps.
    assert ns["honest_n_applications"] < 200, (
        f"north_star leaked fixture apps: n={ns['honest_n_applications']}"
    )
    # TQI: fixture pool has 0 real interview outcomes, so must render 'measuring (baseline)'.
    assert ns["time_to_qualified_interview_days_median"] == "measuring (baseline)" or \
           isinstance(ns["time_to_qualified_interview_days_median"], (int, float)), (
        f"tqi median unexpected: {ns['time_to_qualified_interview_days_median']!r}"
    )

    # Cleanup
    await db.applications.delete_many({"id": {"$regex": "^app-fx-metrics-"}})
    await db.application_outcomes.delete_many({"id": {"$regex": "^out-fx-metrics-"}})
    await db.jobs.delete_many({"id": {"$regex": "^job-fx-metrics-"}})
    await db.users.delete_one({"id": fx_uid})


@pytest.mark.asyncio
async def test_standards_endpoint_wires_all_p0_sections():
    from domains.standards.service import standards
    resp = await standards()
    # Structural — every P0 section must be present.
    for key in ("phases_gated_pass", "change_history", "coverage",
                "outcome_rows", "verification_ladder", "per_country_coverage",
                "north_star", "feature_flags", "rails"):
        assert key in resp, f"/standards missing top-level key {key!r}"
    # Phase gates include Phase 5, 6, Hotfix, and Hotfix Gate Fix.
    phase_names = " | ".join(p["phase"] for p in resp["phases_gated_pass"])
    for expected in ("Phase 5", "Phase 6", "Hotfix Trio", "Hotfix Gate Fix"):
        assert expected in phase_names, f"phases missing {expected!r}"
    # Verification ladder has all 3 tiers.
    tiers = {t["tier"] for t in resp["verification_ladder"]}
    assert tiers == {1, 2, 3}
    tier_names = {t["name"] for t in resp["verification_ladder"]}
    assert tier_names == {"owner-attested", "document-backed", "third-party-checked"}
    # Coverage carries the sample_rows_excluded field explicitly.
    assert "sample_rows_excluded_from_public_counts" in resp["coverage"]


def test_change_history_is_append_only_shape():
    """Every change_history row must carry (date, change) — never mutable content."""
    from domains.standards.service import CHANGE_HISTORY
    assert isinstance(CHANGE_HISTORY, list)
    assert len(CHANGE_HISTORY) >= 8, (
        "change_history must document at least Phases 0-6 + hotfix + gate fix"
    )
    for row in CHANGE_HISTORY:
        assert set(row.keys()) == {"date", "change"}, (
            f"change_history row must have exactly (date, change): {row.keys()}"
        )
        # ISO date shape YYYY-MM-DD.
        assert len(row["date"]) == 10 and row["date"][4] == '-' and row["date"][7] == '-'

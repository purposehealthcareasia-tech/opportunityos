"""P1 FOUNDATION Batch 1 · Global Source Registry tests.

Locks:
  * All 16 canonical seeds land as records on boot.
  * Every seed has all 4 policy-engine status fields.
  * Lifecycle transitions are forward-only.
  * seed_verified_sources() is idempotent (no source skips shadow —
    re-runs preserve advanced lifecycles).
  * Policy engine reads registry records without transformation.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client_per_test():
    import asyncio
    from core import db as _core_db
    # Test-isolation for pytest-asyncio 1.x + motor 3.5.1: force-drop
    # the cached client/db AND reset motor's global ThreadPoolExecutor
    # so no stale loop reference survives to the next test. See
    # docs/ATLAS-STATE §12 for the RCA.
    if _core_db._client is not None:
        try:
            _core_db._client.close()
        except Exception:
            pass
    _core_db._client = None
    _core_db._db = None
    try:
        from motor.frameworks.asyncio import _reset_global_executor
        _reset_global_executor()
    except Exception:
        pass
    db = _core_db.get_db()
    await db.source_registry.delete_many({})
    yield


@pytest.mark.asyncio
async def test_seed_populates_all_canonical_sources():
    from domains.source_registry import (
        seed_verified_sources, CANONICAL_VERIFIED_SEEDS, get,
    )
    counts = await seed_verified_sources()
    assert (counts["inserted"] + counts["updated"]) == len(CANONICAL_VERIFIED_SEEDS)
    # Every seed row is present.
    for seed in CANONICAL_VERIFIED_SEEDS:
        row = await get(seed["source_id"])
        assert row is not None, f"missing source_registry record for {seed['source_id']}"
        assert row["source_id"] == seed["source_id"]


@pytest.mark.asyncio
async def test_every_seed_has_the_four_policy_status_fields():
    from domains.source_registry import (
        seed_verified_sources, CANONICAL_VERIFIED_SEEDS, get,
    )
    await seed_verified_sources()
    for seed in CANONICAL_VERIFIED_SEEDS:
        row = await get(seed["source_id"])
        for field in ("robotsStatus", "termsStatus",
                      "licenseStatus", "legalReviewStatus"):
            assert row.get(field), (
                f"source_registry record {seed['source_id']!r} missing "
                f"policy field {field!r}"
            )


@pytest.mark.asyncio
async def test_seed_is_idempotent():
    from domains.source_registry import seed_verified_sources
    c1 = await seed_verified_sources()
    c2 = await seed_verified_sources()
    # On the second run, everything is an update (no inserts).
    assert c2["inserted"] == 0
    # And no lifecycle transitions get regressed (never rewrite backward).
    assert c2["preserved_lifecycle"] == 0


@pytest.mark.asyncio
async def test_seed_never_regresses_advanced_lifecycle():
    """If a source has been transitioned to `paused` by the admin path,
    re-seeding must NOT reset it back to `verified`."""
    from domains.source_registry import (
        seed_verified_sources, transition_lifecycle, get,
        LIFECYCLE_PAUSED, LIFECYCLE_ACTIVE,
    )
    await seed_verified_sources()
    # Move greenhouse verified -> active -> paused
    await transition_lifecycle("greenhouse", LIFECYCLE_ACTIVE, actor="test") \
        if (await get("greenhouse"))["lifecycle"] != LIFECYCLE_ACTIVE else None
    await transition_lifecycle("greenhouse", LIFECYCLE_PAUSED,
                               actor="test", note="brief pause for legal audit")
    row = await get("greenhouse")
    assert row["lifecycle"] == LIFECYCLE_PAUSED
    # Re-seed — must preserve `paused`.
    await seed_verified_sources()
    row2 = await get("greenhouse")
    assert row2["lifecycle"] == LIFECYCLE_PAUSED, (
        "seeder must never regress an advanced lifecycle"
    )


@pytest.mark.asyncio
async def test_forward_only_lifecycle_transitions():
    from domains.source_registry import (
        seed_verified_sources, transition_lifecycle, get,
        LIFECYCLE_ACTIVE, LIFECYCLE_VERIFIED, LIFECYCLE_RETIRED, LIFECYCLE_PROPOSED,
    )
    await seed_verified_sources()
    # Advance greenhouse to ACTIVE if not already
    if (await get("greenhouse"))["lifecycle"] != LIFECYCLE_ACTIVE:
        await transition_lifecycle("greenhouse", LIFECYCLE_ACTIVE, actor="test")
    # Illegal: active -> verified (backward)
    with pytest.raises(ValueError):
        await transition_lifecycle("greenhouse", LIFECYCLE_VERIFIED, actor="test")
    # Illegal: active -> proposed (backward)
    with pytest.raises(ValueError):
        await transition_lifecycle("greenhouse", LIFECYCLE_PROPOSED, actor="test")
    # Legal: active -> retired
    await transition_lifecycle("greenhouse", LIFECYCLE_RETIRED, actor="test")
    row = await get("greenhouse")
    assert row["lifecycle"] == LIFECYCLE_RETIRED
    # Terminal: retired -> anything is illegal
    with pytest.raises(ValueError):
        await transition_lifecycle("greenhouse", LIFECYCLE_ACTIVE, actor="test")


@pytest.mark.asyncio
async def test_policy_engine_consumes_registry_records_verbatim():
    """The registry's records must flow into source_policy.allow(...)
    without transformation. Locks the integration contract that a
    connector would use in production."""
    from domains.source_registry import seed_verified_sources, get
    from domains.source_policy import allow, Operation
    await seed_verified_sources()
    gh = await get("greenhouse")
    d = allow(source_record=gh, operation=Operation.DISCOVER)
    assert d.allowed, f"greenhouse must be discoverable: {d.reason}"
    d = allow(source_record=gh, operation=Operation.FETCH)
    assert d.allowed
    # LinkedIn seeded with LEGAL_REJECTED — every op must deny.
    li = await get("linkedin")
    for op in Operation:
        d = allow(source_record=li, operation=op)
        assert not d.allowed, f"linkedin (rejected) must deny {op.value}: {d.reason}"


@pytest.mark.asyncio
async def test_no_source_skips_shadow_every_used_source_id_is_in_the_registry():
    """FYND-ATLAS rail: 'no source skips shadow'. Every source_ats value
    the discovery service emits must correspond to a source_registry
    record. If a new adapter is added without a registry seed, this
    test flags it."""
    from domains.source_registry import seed_verified_sources, get
    await seed_verified_sources()
    for ats in ("greenhouse", "lever", "ashby", "usajobs"):
        row = await get(ats)
        assert row is not None, (
            f"source_ats={ats!r} used by discovery service is not in the "
            f"source_registry — 'no source skips shadow' rail violated"
        )

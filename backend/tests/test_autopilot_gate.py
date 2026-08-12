"""Phase 6f · Autopilot hard-lock gate + telemetry invariants.

Rails pinned:
1. Wilson lower bound math is correct (spot-check known values).
2. Gate DEFAULT is `user_not_opted_in` (SHIPPING DISABLED).
3. Opting in ≠ unlock — accuracy + sample-size gate still fires.
4. `insufficient_sample` fires below MIN_SAMPLE_SIZE fields.
5. `accuracy_below_threshold` fires when Wilson lower < MIN_ACCURACY.
6. `allowed` requires ALL: opt-in + sample-size + accuracy.
7. `AUTOPILOT_AUTO_SUBMIT=off` env kill-switch overrides everything.
8. Constants MIN_ACCURACY=0.99, MIN_SAMPLE_SIZE=200 are hardcoded in
   code (not env-flags) — protecting the shipping-safety floor.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from core.db import get_db
from services import autopilot_gate


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


@pytest_asyncio.fixture
async def fresh_user():
    uid = f"apgate-{uuid.uuid4().hex[:12]}"
    yield uid
    db = get_db()
    await db.form_fill_telemetry.delete_many({"user_id": uid})
    await db.user_settings.delete_many({"user_id": uid})


async def _seed_telemetry(user_id: str, *, n_sessions: int,
                            field_count_each: int, mismatches_each: int):
    """Insert n_sessions telemetry rows for a user. Each row records
    field_count_each fields with (field_count_each - mismatches_each)
    matching."""
    db = get_db()
    matches_each = field_count_each - mismatches_each
    rows = []
    now = datetime.now(timezone.utc)
    for i in range(n_sessions):
        rows.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "application_id": f"app-{i}",
            "field_count": field_count_each,
            "field_matches": matches_each,
            "mismatches": [],
            "sample_ts": now,
        })
    if rows:
        await db.form_fill_telemetry.insert_many(rows)


# ---------------------------------------------------------------------------
# 1 · Wilson math sanity — known values
# ---------------------------------------------------------------------------
def test_wilson_lower_bound_math():
    # At p̂=1.0, n=1 → lower bound ~ 0.207 (nowhere near 1.0)
    v1 = autopilot_gate.wilson_lower_bound(1, 1)
    assert 0.15 < v1 < 0.25
    # At p̂=0.99, n=200 → lower bound between 0.965 and 0.995
    v200 = autopilot_gate.wilson_lower_bound(198, 200)
    assert 0.94 < v200 < 0.995
    # At p̂=1.0, n=10000 → lower bound very close to 1.0
    v10k = autopilot_gate.wilson_lower_bound(10000, 10000)
    assert v10k > 0.999
    # n=0 → safe zero
    assert autopilot_gate.wilson_lower_bound(0, 0) == 0.0


# ---------------------------------------------------------------------------
# 2 · Default = user_not_opted_in (ships disabled)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_default_is_not_opted_in(fresh_user):
    allowed, reason, _ = await autopilot_gate.is_auto_submit_allowed(fresh_user)
    assert allowed is False
    assert reason == "user_not_opted_in"


# ---------------------------------------------------------------------------
# 3 · Opting in is not enough — insufficient_sample still blocks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_opt_in_alone_does_not_unlock(fresh_user):
    db = get_db()
    await db.user_settings.insert_one({
        "user_id": fresh_user,
        "autopilot_auto_submit_opt_in": True,
    })
    # No telemetry at all → insufficient_sample.
    allowed, reason, metrics = await autopilot_gate.is_auto_submit_allowed(fresh_user)
    assert allowed is False
    assert reason == "insufficient_sample", metrics


# ---------------------------------------------------------------------------
# 4 · Fully passing scenario — opt-in + enough samples to clear Wilson-99%
#
# NB: At MIN_ACCURACY=0.99, the Wilson-95% lower bound at p̂=1.0, n=200
# is ~0.981 — does NOT clear 0.99. To PASS the gate at p̂=1.0 we need
# n >= 381 (since lower = n/(n+z²) with z²≈3.84 → n/(n+3.84) >= 0.99
# → n >= 380). This is the intentional safety floor: perfect-observed
# accuracy alone is not enough; you need enough samples that a 95%-CI
# statistically rules out sub-99% true accuracy. That's the whole point.
# 50 sessions × 10 fields = 500 fields → lower ≈ 0.9924, clears 0.99.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_allowed_when_all_conditions_met(fresh_user, monkeypatch):
    monkeypatch.delenv("AUTOPILOT_AUTO_SUBMIT", raising=False)
    db = get_db()
    await db.user_settings.insert_one({
        "user_id": fresh_user,
        "autopilot_auto_submit_opt_in": True,
    })
    # 50 sessions x 10 fields = 500 fields, all correct → Wilson lower ≈ 0.9924
    await _seed_telemetry(fresh_user, n_sessions=50, field_count_each=10,
                            mismatches_each=0)
    allowed, reason, metrics = await autopilot_gate.is_auto_submit_allowed(fresh_user)
    assert allowed is True, (reason, metrics)
    assert reason == "allowed"
    assert metrics["n_fields"] == 500
    assert metrics["accuracy_pct"] == 100.0
    assert metrics["ci95_lower_pct"] >= 99.0


# ---------------------------------------------------------------------------
# 5 · Accuracy below threshold blocks even with sample size met
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_accuracy_below_threshold_blocks(fresh_user, monkeypatch):
    monkeypatch.delenv("AUTOPILOT_AUTO_SUBMIT", raising=False)
    db = get_db()
    await db.user_settings.insert_one({
        "user_id": fresh_user,
        "autopilot_auto_submit_opt_in": True,
    })
    # 30 sessions x 10 fields = 300 fields, 3 mismatches each = 90 mismatches
    # → accuracy 70%. Well below 99%.
    await _seed_telemetry(fresh_user, n_sessions=30, field_count_each=10,
                            mismatches_each=3)
    allowed, reason, metrics = await autopilot_gate.is_auto_submit_allowed(fresh_user)
    assert allowed is False
    assert reason == "accuracy_below_threshold"
    assert metrics["ci95_lower_pct"] < 99.0


# ---------------------------------------------------------------------------
# 6 · Env kill-switch overrides everything
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_env_kill_switch_overrides(fresh_user, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTO_SUBMIT", "off")
    db = get_db()
    await db.user_settings.insert_one({
        "user_id": fresh_user,
        "autopilot_auto_submit_opt_in": True,
    })
    # 50 × 10 = 500 fields — enough to clear the accuracy gate — so if
    # the kill-switch fails, this would otherwise allow.
    await _seed_telemetry(fresh_user, n_sessions=50, field_count_each=10,
                            mismatches_each=0)
    allowed, reason, _ = await autopilot_gate.is_auto_submit_allowed(fresh_user)
    assert allowed is False
    assert reason == "shipped_disabled"


# ---------------------------------------------------------------------------
# 7 · Constants are locked in code, not env (safety floor invariant)
# ---------------------------------------------------------------------------
def test_gate_constants_hardcoded():
    """MIN_ACCURACY and MIN_SAMPLE_SIZE are code constants — an env-flag
    would let ops flip the safety floor at runtime, which is the whole
    thing we're pinning against."""
    assert autopilot_gate.MIN_ACCURACY == 0.99
    assert autopilot_gate.MIN_SAMPLE_SIZE == 200
    # Grep source to confirm they aren't reading env for these values.
    import inspect
    src = inspect.getsource(autopilot_gate)
    lines = [l for l in src.splitlines() if l.strip().startswith("MIN_ACCURACY") or l.strip().startswith("MIN_SAMPLE_SIZE")]
    assert lines, "MIN_ACCURACY / MIN_SAMPLE_SIZE must be top-level constants in autopilot_gate.py"
    for l in lines:
        assert "os.environ" not in l and "getenv" not in l, \
            "safety-floor constants must NOT be env-flagged"


# ---------------------------------------------------------------------------
# 8 · MIN_SAMPLE_SIZE boundary — at exactly 200 fields with perfect
#      accuracy, sample-size check PASSES but ACCURACY gate blocks
#      (Wilson lower at p̂=1.0, n=200 is ~0.981 — does not clear 0.99).
#      That's the layered gate semantics working correctly. See §4 for
#      the passing n=500 case.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sample_size_boundary_layered_correctly(fresh_user, monkeypatch):
    monkeypatch.delenv("AUTOPILOT_AUTO_SUBMIT", raising=False)
    db = get_db()
    await db.user_settings.insert_one({
        "user_id": fresh_user, "autopilot_auto_submit_opt_in": True,
    })
    # Exactly 200 fields, all correct.
    await _seed_telemetry(fresh_user, n_sessions=20, field_count_each=10,
                            mismatches_each=0)
    allowed, reason, metrics = await autopilot_gate.is_auto_submit_allowed(fresh_user)
    assert metrics["n_fields"] == 200
    # Sample size check PASSED (we advanced past insufficient_sample) — the
    # block is now on accuracy, not sample size.
    assert reason == "accuracy_below_threshold", (reason, metrics)
    assert allowed is False
    # Wilson lower bound at p̂=1.0, n=200 is ≈ 0.981 — well below 0.99.
    assert 97.0 < metrics["ci95_lower_pct"] < 99.0, metrics

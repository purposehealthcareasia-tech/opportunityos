"""P1 FOUNDATION Batch 4 · Item 1 · Freshness ≠ Liveness tests.

Locks the hard invariants:

  * `apply_transition` — unknown→active REQUIRES evidence with
    `check` (str), `at` (ISO), `observed` (str|dict). Missing any
    field raises `LivenessTransitionError`.
  * Every in-edge to `active` (from any state) requires evidence —
    closes the `temporarily_unreachable → active` retry-success gap.
  * `inactive` is terminal — no egress permitted.
  * `is_fresh` — freshness stamp within per-source budget.
  * `enforce_liveness_before_dispatch` — the prepare/approve gate.
    Refuses when state != active OR evidence missing OR stale.
  * NO LLM in liveness path (static grep guard).
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from domains.liveness import (
    LivenessState, LivenessTransitionError, LivenessGateError,
    apply_transition, freshness_block, is_fresh, budget_for,
    enforce_liveness_before_dispatch,
    FRESHNESS_BUDGET_S, DEFAULT_FRESHNESS_BUDGET_S,
)


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_and_jobs():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    db = _core_db.get_db()
    await db.jobs.delete_many({"canonical_key": {"$regex": "^test-liveness::"}})
    yield


# ------------------------------------------------------------------
# Invariant: unknown → active REQUIRES evidence
# ------------------------------------------------------------------
def _good_evidence():
    return {
        "check": "connector_fetch_all_returned_id",
        "at": datetime.now(timezone.utc).isoformat(),
        "observed": "id 42 present in greenhouse response for token=acme",
    }


def test_unknown_to_active_requires_evidence():
    # Without evidence — raises.
    with pytest.raises(LivenessTransitionError, match="evidence_required"):
        apply_transition(current_block=None,
                         new_state=LivenessState.ACTIVE, evidence=None)
    # With bare dict (no keys) — raises.
    with pytest.raises(LivenessTransitionError, match="evidence_missing_or_blank"):
        apply_transition(current_block=None,
                         new_state=LivenessState.ACTIVE, evidence={})
    # With evidence missing `observed` — raises.
    bad = _good_evidence(); bad.pop("observed")
    with pytest.raises(LivenessTransitionError, match="observed"):
        apply_transition(current_block=None,
                         new_state=LivenessState.ACTIVE, evidence=bad)
    # With evidence missing `at` — raises.
    bad = _good_evidence(); bad.pop("at")
    with pytest.raises(LivenessTransitionError, match="at"):
        apply_transition(current_block=None,
                         new_state=LivenessState.ACTIVE, evidence=bad)
    # With evidence missing `check` — raises.
    bad = _good_evidence(); bad.pop("check")
    with pytest.raises(LivenessTransitionError, match="check"):
        apply_transition(current_block=None,
                         new_state=LivenessState.ACTIVE, evidence=bad)


def test_unknown_to_active_with_good_evidence_permitted():
    block = apply_transition(
        current_block=None,
        new_state=LivenessState.ACTIVE,
        evidence=_good_evidence(),
    )
    assert block["state"] == "active"
    assert block["evidence"]["check"] == "connector_fetch_all_returned_id"
    assert block["updated_at"], "updated_at must be stamped"


def test_every_in_edge_to_active_requires_evidence():
    """Not just unknown→active. temporarily_unreachable → active is
    also gated: a retry-success MUST cite what it saw."""
    unreachable = {"state": "temporarily_unreachable", "evidence": None,
                   "updated_at": "2026-08-13T00:00:00+00:00"}
    with pytest.raises(LivenessTransitionError):
        apply_transition(current_block=unreachable,
                         new_state=LivenessState.ACTIVE, evidence=None)
    # With good evidence — permitted.
    ok = apply_transition(current_block=unreachable,
                          new_state=LivenessState.ACTIVE,
                          evidence=_good_evidence())
    assert ok["state"] == "active"


# ------------------------------------------------------------------
# Invariant: inactive is terminal
# ------------------------------------------------------------------
def test_inactive_is_terminal():
    dead = {"state": "inactive", "evidence": _good_evidence(),
            "updated_at": "2026-08-01T00:00:00+00:00"}
    # Any transition OUT of inactive raises.
    for target in (LivenessState.ACTIVE, LivenessState.UNKNOWN,
                   LivenessState.TEMPORARILY_UNREACHABLE,
                   LivenessState.REQUIRES_CANDIDATE_VERIFICATION):
        with pytest.raises(LivenessTransitionError, match="terminal_state"):
            apply_transition(current_block=dead, new_state=target,
                             evidence=_good_evidence())
    # inactive → inactive is a no-op (permitted, same state).
    same = apply_transition(current_block=dead,
                            new_state=LivenessState.INACTIVE, evidence=None)
    assert same["state"] == "inactive"


# ------------------------------------------------------------------
# Enum coverage
# ------------------------------------------------------------------
def test_unknown_new_state_raises():
    with pytest.raises(LivenessTransitionError, match="unknown_liveness_state"):
        apply_transition(current_block=None,
                         new_state="pending_founder_approval",
                         evidence=_good_evidence())


# ------------------------------------------------------------------
# Freshness
# ------------------------------------------------------------------
def test_freshness_budget_per_source():
    assert budget_for("greenhouse") == 6 * 3600
    assert budget_for("usajobs")    == 24 * 3600
    # Unknown source falls back to default.
    assert budget_for("some_unknown_source") == DEFAULT_FRESHNESS_BUDGET_S


def test_is_fresh_true_when_within_budget():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=30)).isoformat()
    fresh = freshness_block("greenhouse", last_polled_at_iso=recent)
    assert is_fresh(fresh) is True


def test_is_fresh_false_when_past_budget():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=7)).isoformat()  # > 6h greenhouse budget
    stale = freshness_block("greenhouse", last_polled_at_iso=old)
    assert is_fresh(stale) is False


def test_is_fresh_false_on_missing_stamp():
    assert is_fresh({}) is False
    assert is_fresh(None) is False


# ------------------------------------------------------------------
# Prepare/approve gate
# ------------------------------------------------------------------
async def _insert_test_job(*, job_id, liveness, freshness):
    from core.db import get_db
    db = get_db()
    await db.jobs.insert_one({
        "id": job_id,
        "canonical_key": f"test-liveness::{job_id}",
        "title": "SWE", "company_name": "Test",
        "liveness": liveness,
        "freshness": freshness,
        "is_sample": False,
        "status": "live",
    })


@pytest.mark.asyncio
async def test_gate_permits_active_and_fresh():
    fresh_stamp = freshness_block(
        "greenhouse",
        last_polled_at_iso=datetime.now(timezone.utc).isoformat(),
    )
    await _insert_test_job(
        job_id="job-fresh-active",
        liveness=apply_transition(current_block=None,
                                  new_state=LivenessState.ACTIVE,
                                  evidence=_good_evidence()),
        freshness=fresh_stamp,
    )
    liveness = await enforce_liveness_before_dispatch("job-fresh-active")
    assert liveness["state"] == "active"
    assert liveness["evidence"]["check"]


@pytest.mark.asyncio
async def test_gate_blocks_when_not_active():
    fresh_stamp = freshness_block(
        "greenhouse",
        last_polled_at_iso=datetime.now(timezone.utc).isoformat(),
    )
    await _insert_test_job(
        job_id="job-unknown",
        liveness={"state": "unknown", "evidence": None,
                  "updated_at": datetime.now(timezone.utc).isoformat()},
        freshness=fresh_stamp,
    )
    with pytest.raises(LivenessGateError) as exc:
        await enforce_liveness_before_dispatch("job-unknown")
    assert "liveness_not_active" in exc.value.reason


@pytest.mark.asyncio
async def test_gate_blocks_when_evidence_missing():
    """A row with state=active but no evidence is a defect — gate MUST
    block. This closes the 'silent update' path where a background job
    incorrectly marks active without observed evidence."""
    fresh_stamp = freshness_block(
        "greenhouse",
        last_polled_at_iso=datetime.now(timezone.utc).isoformat(),
    )
    await _insert_test_job(
        job_id="job-defective-active",
        liveness={"state": "active", "evidence": None,
                  "updated_at": datetime.now(timezone.utc).isoformat()},
        freshness=fresh_stamp,
    )
    with pytest.raises(LivenessGateError) as exc:
        await enforce_liveness_before_dispatch("job-defective-active")
    assert exc.value.reason == "liveness_no_evidence"


@pytest.mark.asyncio
async def test_gate_blocks_when_freshness_stale():
    stale = freshness_block(
        "greenhouse",
        last_polled_at_iso=(datetime.now(timezone.utc)
                            - timedelta(hours=25)).isoformat(),
    )
    await _insert_test_job(
        job_id="job-stale",
        liveness=apply_transition(current_block=None,
                                  new_state=LivenessState.ACTIVE,
                                  evidence=_good_evidence()),
        freshness=stale,
    )
    with pytest.raises(LivenessGateError) as exc:
        await enforce_liveness_before_dispatch("job-stale")
    assert exc.value.reason == "freshness_stale"


@pytest.mark.asyncio
async def test_gate_blocks_when_job_missing():
    with pytest.raises(LivenessGateError) as exc:
        await enforce_liveness_before_dispatch("no-such-job")
    assert exc.value.reason == "job_not_found"


# ------------------------------------------------------------------
# NO LLM
# ------------------------------------------------------------------
def test_liveness_module_has_no_llm_calls():
    p = (pathlib.Path(__file__).resolve().parent.parent
         / "domains" / "liveness" / "__init__.py")
    text = p.read_text(encoding="utf-8")
    forbidden = ("openai", "anthropic", "gemini",
                 "emergentintegrations", "generate_with_llm",
                 "chat.completions")
    hits = [f for f in forbidden if f in text.lower()]
    assert not hits, f"liveness module must NOT reference LLM SDKs: {hits}"

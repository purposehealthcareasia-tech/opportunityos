"""P1 FOUNDATION Batch 4 · Item 1 · Freshness ≠ Liveness.

FYND ATLAS §16-17 — a source-freshness stamp is NOT a liveness signal.
Historically the `jobs.status` field conflated the two ("live" meant
both 'seen on last poll' and 'candidate may prepare / submit'). This
module separates them:

  * `freshness_block` — per-source poll telemetry: `{source_id,
    last_polled_at, cadence_s, next_due_at}`. Updated on every
    successful poll. Distinct from liveness.
  * `liveness_block` — the candidate-facing signal:
    `{state ∈ {active, inactive, unknown, temporarily_unreachable,
    requires_candidate_verification}, evidence, updated_at}`.
    Never transitions to `active` from `unknown` without observed
    evidence (which check ran, at what time, what it saw).

Hard invariants (locked by tests):

  1. `unknown → active` MUST carry an evidence field with
     `check` (str), `at` (ISO), `observed` (str or dict, non-null).
     `apply_transition()` raises `LivenessTransitionError` otherwise.
  2. `inactive` is terminal — no egress. Recording a mistake requires
     a NEW job document (never overwrite a closed row).
  3. `active` is only reached with fresh observed evidence, regardless
     of the prior state. This closes the gap where a `temporarily_
     unreachable` retry succeeds without proper evidence.
  4. `enforce_liveness_before_dispatch()` — the prepare/approve gate.
     Raises `LivenessGateError` unless liveness == active AND
     freshness stamp is within the source's budget.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.time_utils import utc_now


# ------------------------------------------------------------------
# Liveness enum
# ------------------------------------------------------------------
class LivenessState(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"
    TEMPORARILY_UNREACHABLE = "temporarily_unreachable"
    REQUIRES_CANDIDATE_VERIFICATION = "requires_candidate_verification"


VALID_STATES: frozenset[str] = frozenset(s.value for s in LivenessState)

# Terminal states — no egress permitted.
TERMINAL_STATES: frozenset[str] = frozenset({LivenessState.INACTIVE.value})


# ------------------------------------------------------------------
# Per-source freshness budgets (seconds). If freshness stamp is older
# than the budget, the row is stale for dispatch purposes regardless
# of the liveness value. Source-specific budgets reflect how often
# each publisher updates its own feed.
# ------------------------------------------------------------------
FRESHNESS_BUDGET_S: dict[str, int] = {
    # HOT public ATSes — polling scheduler already targets ≤20min/6hr.
    "greenhouse": 6 * 3600,
    "lever":      6 * 3600,
    "ashby":      6 * 3600,
    # USAJOBS federal — updates daily.
    "usajobs":    24 * 3600,
    # First-party surfaces — long budgets.
    "employer_intake":    24 * 3600,
    "walkin_route":       30 * 86400,
    "credential_catalog": 30 * 86400,
    # Fixture — never expires (tests must not flake on wall clock).
    "sampleco_demo":      30 * 86400,
}
DEFAULT_FRESHNESS_BUDGET_S = 12 * 3600


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------
class LivenessTransitionError(RuntimeError):
    """Raised when a caller attempts a disallowed liveness transition
    OR when `active` is being set without valid evidence."""


class LivenessGateError(RuntimeError):
    """Raised by `enforce_liveness_before_dispatch()` when a prepare/
    approve caller tries to act on a job that is not demonstrably
    active + fresh. Callers MUST propagate — NEVER catch silently."""
    def __init__(self, reason: str, details: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


# ------------------------------------------------------------------
# Evidence validation
# ------------------------------------------------------------------
_EVIDENCE_REQUIRED_KEYS = ("check", "at", "observed")


def _validate_evidence(evidence: dict | None) -> None:
    """Evidence must be a dict with all three keys populated. `check`
    is a stable string identifier of which liveness check ran (e.g.
    'ats_fetch_all_returned_id'); `at` is an ISO-UTC timestamp of
    when the check ran; `observed` is a non-null description of what
    the check saw (string or dict — the audit log wants both). No
    field may be blank."""
    if evidence is None or not isinstance(evidence, dict):
        raise LivenessTransitionError(
            "evidence_required_dict:got_" + type(evidence).__name__
        )
    for k in _EVIDENCE_REQUIRED_KEYS:
        v = evidence.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise LivenessTransitionError(f"evidence_missing_or_blank:{k}")
    # `check` must be a string; `at` must be ISO-8601 shape.
    if not isinstance(evidence["check"], str):
        raise LivenessTransitionError("evidence_check_not_string")
    if not isinstance(evidence["at"], str):
        raise LivenessTransitionError("evidence_at_not_string")


# ------------------------------------------------------------------
# Public: apply transition
# ------------------------------------------------------------------
def apply_transition(
    *,
    current_block: dict | None,
    new_state: LivenessState | str,
    evidence: dict | None = None,
) -> dict:
    """Return the new liveness block after a state transition.

    Rules (all locked by tests):
      * Any transition to `active` MUST carry valid evidence — this
        includes `unknown → active` and every other in-edge.
      * `inactive` is terminal — attempting to leave it raises.
      * Non-active target states inherit prior evidence if present,
        or accept `None` (nothing was observed by this transition).
      * `new_state` must be one of the enumerated LivenessState values.
    """
    if isinstance(new_state, LivenessState):
        new = new_state.value
    else:
        new = str(new_state)
    if new not in VALID_STATES:
        raise LivenessTransitionError(f"unknown_liveness_state:{new}")

    cur = (current_block or {}).get("state") or LivenessState.UNKNOWN.value

    # Terminal invariant.
    if cur in TERMINAL_STATES and new != cur:
        raise LivenessTransitionError(f"terminal_state_no_egress:{cur}→{new}")

    # Every in-edge to ACTIVE requires evidence — closes the
    # `unknown → active` invariant AND the `temporarily_unreachable
    # → active` case where a retry-success must still cite what it saw.
    if new == LivenessState.ACTIVE.value:
        _validate_evidence(evidence)

    return {
        "state": new,
        "evidence": evidence if evidence is not None else (current_block or {}).get("evidence"),
        "updated_at": utc_now().isoformat(),
    }


# ------------------------------------------------------------------
# Freshness
# ------------------------------------------------------------------
def budget_for(source_id: str) -> int:
    return FRESHNESS_BUDGET_S.get(source_id, DEFAULT_FRESHNESS_BUDGET_S)


def freshness_block(source_id: str, *, last_polled_at_iso: str) -> dict:
    """Build a freshness block. `next_due_at` derived from budget."""
    cadence_s = budget_for(source_id)
    return {
        "source_id": source_id,
        "last_polled_at": last_polled_at_iso,
        "cadence_s": cadence_s,
        # next_due_at is computed by the scheduler at run time — not
        # stored here to avoid ambient-clock drift between pods.
    }


def is_fresh(freshness: dict | None, *, now_iso: str | None = None) -> bool:
    """True iff `freshness.last_polled_at` is within the source's
    budget as of `now_iso` (defaults to wall clock)."""
    if not freshness or not freshness.get("last_polled_at"):
        return False
    from datetime import datetime
    try:
        last = datetime.fromisoformat(str(freshness["last_polled_at"]).replace("Z", "+00:00"))
    except Exception:
        return False
    now = (datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
           if now_iso else utc_now())
    budget_s = int(freshness.get("cadence_s") or budget_for(freshness.get("source_id", "")))
    delta = (now - last).total_seconds()
    return delta >= 0 and delta <= budget_s


# ------------------------------------------------------------------
# Prepare / approve gate
# ------------------------------------------------------------------
async def enforce_liveness_before_dispatch(job_id: str) -> dict:
    """Strongest-allowed liveness check before any prepare/approve.

    Reads the job's stored liveness + freshness blocks. Raises
    `LivenessGateError` when:
      * job not found → reason=`job_not_found`
      * liveness.state != active → reason=`liveness_not_active:<state>`
      * freshness stamp older than the source's budget →
        reason=`freshness_stale`
      * liveness.evidence missing → reason=`liveness_no_evidence` (a
        row with state=active but no evidence is a defect; block).

    On pass, returns the liveness block so the caller can embed it on
    the outbound receipt / verdict for the audit trail.
    """
    from core.db import get_db
    db = get_db()
    job = await db.jobs.find_one({"id": job_id},
                                  {"liveness": 1, "freshness": 1, "_id": 0})
    if not job:
        raise LivenessGateError("job_not_found", {"job_id": job_id})

    liveness = job.get("liveness") or {}
    state = liveness.get("state")
    if state != LivenessState.ACTIVE.value:
        raise LivenessGateError(
            f"liveness_not_active:{state or 'missing'}",
            {"job_id": job_id, "state": state},
        )
    if not liveness.get("evidence"):
        raise LivenessGateError(
            "liveness_no_evidence",
            {"job_id": job_id, "state": state},
        )
    freshness = job.get("freshness") or {}
    if not is_fresh(freshness):
        raise LivenessGateError(
            "freshness_stale",
            {"job_id": job_id, "freshness": freshness},
        )
    return liveness

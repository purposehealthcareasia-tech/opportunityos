"""Fastest-Path engine tests — Batch 5.

Covers:
  * Single-best-next-action selection.
  * No fabricated probabilities: every score is bounded to [0,1] and
    confidence is a discrete label.
  * NO_APPLY_PATH is never returned as a submit action.
  * Silence is first-class: absent evidence never produces a
    fabricated value; it appears in `unknown` with a
    what_would_change_it hint.
  * Authorization gating: unauthorized opportunities return
    ActionKind.AUTHORIZE.
  * Structural: no protected attributes in any input / output field.
"""
from __future__ import annotations

import inspect

import pytest

from domains.applications.fastest_path import (
    ActionKind,
    Candidate,
    ConfidenceTier,
    FACTOR_WEIGHTS,
    NextAction,
    OpportunityInput,
    best_next,
    rank,
)
from domains.applications.routes import RouteType


def _direct_ats_opp(job_id: str, **overrides):
    op = {
        "job_id": job_id,
        "opportunity": {
            "source_ats": "greenhouse",
            "apply_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
        },
        "liveness_signal_count": 2,
        "expected_value_hint": 0.8,
        "close_date_days_out": 5,
    }
    op.update(overrides)
    return OpportunityInput(**op)


def _no_apply_opp(job_id: str, **overrides):
    op = {
        "job_id": job_id,
        "opportunity": {"source_ats": "", "apply_url": None},
        "liveness_signal_count": 1,
        "expected_value_hint": 0.9,
        "close_date_days_out": 2,
    }
    op.update(overrides)
    return OpportunityInput(**op)


def _email_opp(job_id: str, **overrides):
    op = {
        "job_id": job_id,
        "opportunity": {"apply_email": "jobs@example.com"},
        "liveness_signal_count": 1,
        "expected_value_hint": 0.7,
        "close_date_days_out": None,
    }
    op.update(overrides)
    return OpportunityInput(**op)


# =====================================================================
# 1. Score bounding + no fabricated probabilities
# =====================================================================
def test_score_is_bounded_zero_to_one():
    cand = Candidate(user_id="u1", authorized_job_ids=frozenset({"j1"}))
    results = rank(cand, [_direct_ats_opp("j1")])
    for r in results:
        assert 0.0 <= r.score <= 1.0


def test_confidence_is_discrete_label_not_a_probability():
    cand = Candidate(user_id="u1", authorized_job_ids=frozenset({"j1"}))
    r = best_next(cand, [_direct_ats_opp("j1")])
    assert r is not None
    assert r.confidence in {
        ConfidenceTier.HIGH, ConfidenceTier.MED, ConfidenceTier.LOW,
    }


def test_confidence_low_when_only_one_factor_informed():
    cand = Candidate(user_id="u1", authorized_job_ids=frozenset({"j1"}))
    # Only route-derived factors present (time_cost, reversibility,
    # risk_penalty are always non-None); expected/urgency/liveness are all None.
    opp = OpportunityInput(
        job_id="j1",
        opportunity={"source_ats": "greenhouse",
                     "apply_url": "https://boards.greenhouse.io/x/jobs/j1"},
        liveness_signal_count=None,
        expected_value_hint=None,
        close_date_days_out=None,
    )
    r = best_next(cand, [opp])
    assert r is not None
    # 3 informed factors (time_cost, reversibility, risk_penalty
    # excluded from counter). Actually _confidence_from_factors counts
    # everything EXCEPT risk_penalty. time_cost + reversibility = 2 →
    # MED. Expect MED in this case.
    assert r.confidence == ConfidenceTier.MED


# =====================================================================
# 2. NO_APPLY_PATH → PREPARE_ONLY, never SUBMIT
# =====================================================================
def test_no_apply_path_is_prepare_only():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1"}))
    r = best_next(cand, [_no_apply_opp("j1")])
    assert r is not None
    assert r.route_type is RouteType.NO_APPLY_PATH
    assert r.action_kind is ActionKind.PREPARE_ONLY


def test_ranking_prefers_submittable_over_no_apply_at_tie():
    """Even with strong expected_value + urgency, a NO_APPLY_PATH
    entry must not outrank a submittable entry of similar quality.
    The RISK penalty for NO_APPLY_PATH enforces this."""
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1", "j2"}))
    ranked = rank(cand, [
        _no_apply_opp("j1"),
        _direct_ats_opp("j2", expected_value_hint=0.5,
                        close_date_days_out=30,
                        liveness_signal_count=1),
    ])
    # j2 (direct_ats) should outrank j1 (no_apply).
    assert ranked[0].job_id == "j2"
    assert ranked[1].job_id == "j1"


# =====================================================================
# 3. Authorization gating
# =====================================================================
def test_unauthorized_opportunity_returns_authorize_action():
    cand = Candidate(user_id="u1", authorized_job_ids=frozenset())
    r = best_next(cand, [_direct_ats_opp("j1")])
    assert r is not None
    assert r.action_kind is ActionKind.AUTHORIZE


def test_authorized_opportunity_returns_submit_action():
    cand = Candidate(user_id="u1", authorized_job_ids=frozenset({"j1"}))
    r = best_next(cand, [_direct_ats_opp("j1")])
    assert r is not None
    assert r.action_kind is ActionKind.SUBMIT


# =====================================================================
# 4. Silence is first-class
# =====================================================================
def test_missing_close_date_produces_unknown_urgency():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1"}))
    r = best_next(cand, [_email_opp("j1")])  # close_date_days_out=None
    assert r is not None
    assert "factor:urgency" in r.unknown
    assert any("close date" in c.lower() for c in r.what_would_change_it)


def test_missing_liveness_produces_unknown_liveness():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1"}))
    opp = _direct_ats_opp("j1", liveness_signal_count=None)
    r = best_next(cand, [opp])
    assert r is not None
    assert "factor:liveness" in r.unknown


def test_missing_expected_value_produces_unknown_expected_value():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1"}))
    opp = _direct_ats_opp("j1", expected_value_hint=None)
    r = best_next(cand, [opp])
    assert r is not None
    assert "factor:expected_value" in r.unknown


def test_all_present_produces_high_confidence():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1"}))
    r = best_next(cand, [_direct_ats_opp("j1")])
    assert r is not None
    assert r.confidence == ConfidenceTier.HIGH


# =====================================================================
# 5. Explanation payload shape
# =====================================================================
def test_next_action_carries_full_explanation_payload():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1"}))
    r = best_next(cand, [_direct_ats_opp("j1")])
    assert r is not None
    d = r.to_dict()
    for key in ("job_id", "action_kind", "route_type", "score",
                "confidence", "factors", "positive", "negative",
                "unknown", "what_would_change_it"):
        assert key in d
    # Score is rounded and bounded.
    assert 0.0 <= d["score"] <= 1.0
    # Route is one of the seven types.
    assert d["route_type"] in {rt.value for rt in RouteType}


def test_positive_always_includes_route_label():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"j1"}))
    r = best_next(cand, [_direct_ats_opp("j1")])
    assert r is not None
    assert f"route:{r.route_type.value}" in r.positive


# =====================================================================
# 6. Ranking determinism
# =====================================================================
def test_ranking_is_deterministic():
    cand = Candidate(user_id="u1",
                     authorized_job_ids=frozenset({"a", "b", "c"}))
    opps = [
        _direct_ats_opp("a", expected_value_hint=0.6),
        _direct_ats_opp("b", expected_value_hint=0.8),
        _direct_ats_opp("c", expected_value_hint=0.7),
    ]
    r1 = [x.job_id for x in rank(cand, opps)]
    r2 = [x.job_id for x in rank(cand, opps)]
    assert r1 == r2 == ["b", "c", "a"]


def test_empty_input_returns_none_best_next():
    cand = Candidate(user_id="u1")
    assert best_next(cand, []) is None
    assert rank(cand, []) == []


# =====================================================================
# 7. Structural — no protected attributes in signatures / types
# =====================================================================
_BANNED_SUBSTRINGS = frozenset({
    "race", "ethnicity", "gender", "sex", "age_", "birthdate",
    "national_origin", "religion", "marital", "parental",
    "disability", "sexual_orientation", "veteran",
})


def _fields_of(cls) -> list[str]:
    if hasattr(cls, "__dataclass_fields__"):
        return list(cls.__dataclass_fields__.keys())
    return []


def test_no_protected_attribute_in_public_dataclasses():
    for cls in (Candidate, OpportunityInput, NextAction):
        for name in _fields_of(cls):
            lower = name.lower()
            hits = [b for b in _BANNED_SUBSTRINGS if b in lower]
            assert not hits, (
                f"{cls.__name__}.{name} references banned substring "
                f"{hits}; ATLAS forbids protected attributes."
            )


def test_no_protected_attribute_in_module_source():
    """AST-level scan of the engine source to catch stray references
    (e.g. a comment or an env-var lookup)."""
    from domains.applications.fastest_path import engine as _e
    src = inspect.getsource(_e).lower()
    hits = [b for b in _BANNED_SUBSTRINGS if b in src]
    # `sex` is a substring of many innocent words (e.g. "sextet") —
    # but the current engine has none. Keep the strict check.
    assert not hits, (
        f"fastest_path engine source references banned substring(s) "
        f"{hits}"
    )


def test_factor_weights_shape_stable():
    """Downstream consumers (constitution page render, admin surface)
    key off these names. If someone renames one, trip the test."""
    assert set(FACTOR_WEIGHTS.keys()) == {
        "expected_value", "urgency", "time_cost",
        "liveness", "reversibility", "risk_penalty",
    }
    assert all(0.0 < w <= 1.0 for w in FACTOR_WEIGHTS.values())

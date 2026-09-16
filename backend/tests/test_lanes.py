"""Lanes tests — Batch 6.

Covers the ATLAS lane invariants:

  * 13 registered lanes exactly (Income Now deliberately absent).
  * Stage-1-failed job cannot appear in ANY lane (fail-CLOSED
    across the entire registry, tested against a synthetic row
    with a `fail` outcome).
  * Fastest Credible Response is empty when n < 20; when it
    renders, `requires_confidence_display=True` and every match
    carries n + confidence + "not_a_guarantee".
  * `lawful_source_available=False` surfaces an honest empty
    state with `empty_reason="no_lawful_source_yet"`.
  * Every match's `reason` dict keys are a subset of the lane's
    declared `reason_schema` (drift lock).
  * Selectors are pure — same input, same output.
"""
from __future__ import annotations

import pytest

from domains.lanes import (
    LANE_REGISTRY,
    LaneContext,
    LaneSpec,
    by_id,
    render_all,
    render_lane,
)
from domains.lanes.registry import LaneMatch


NOW = "2026-02-14T10:00:00+00:00"
TODAY = "2026-02-14T00:00:00+00:00"


def _ctx(**overrides) -> LaneContext:
    base = dict(
        candidate_country="US",
        candidate_locations=("San Francisco", "Remote"),
        candidate_remote_ok=True,
        approved_skill_names=frozenset({"python", "sql"}),
        approved_certifications=frozenset({"aws_saa"}),
        needs_sponsorship=False,
        now_utc_iso=NOW,
        today_utc_iso=TODAY,
    )
    base.update(overrides)
    return LaneContext(**base)


def _opp(job_id: str, stage1_pass: bool = True, **fields) -> dict:
    op = {"job_id": job_id, "title": "", "location": "", "skills": [],
          "remote": False, "source_ats": ""}
    if stage1_pass:
        op["stage1_outcomes"] = {"vacancy_open": "pass",
                                  "work_auth": "pass"}
    else:
        op["stage1_outcomes"] = {"vacancy_open": "pass",
                                  "work_auth": "fail"}
    op.update(fields)
    return op


# =====================================================================
# 1. Registry integrity
# =====================================================================
def test_exactly_thirteen_lanes():
    """ATLAS: 13 named lanes. Income Now is deliberately absent
    (no lawful source today)."""
    assert len(LANE_REGISTRY) == 13
    ids = [l.id for l in LANE_REGISTRY]
    assert len(ids) == len(set(ids)), "duplicate lane ids"
    assert "income_now" not in ids


def test_lane_ids_are_stable_string_values():
    """Downstream (URLs, telemetry, receipts) key off these ids."""
    expected = {
        "best_fit", "fastest_credible_response", "local_now",
        "remote_worldwide", "visa_friendly", "sponsorship_possible",
        "new_today", "closing_soon", "government", "internships",
        "apprenticeships", "outside_my_usual_path",
        "one_credential_away",
    }
    assert {l.id for l in LANE_REGISTRY} == expected


def test_every_lane_declares_reason_schema_and_selector():
    for l in LANE_REGISTRY:
        assert isinstance(l, LaneSpec)
        assert callable(l.selector)
        assert l.reason_schema, f"lane {l.id} missing reason_schema"
        assert l.title and l.description


# =====================================================================
# 2. Stage 1 fail-CLOSED invariant across every lane
# =====================================================================
def test_stage1_failed_job_appears_in_no_lane():
    """The single invariant test: a job with any `fail` outcome
    cannot appear in ANY lane, regardless of how strongly it
    would otherwise qualify."""
    ctx = _ctx()
    # Build a maximally attractive row with EVERY signal that
    # would otherwise place it in as many lanes as possible.
    op = _opp(
        "j_bad",
        stage1_pass=False,
        title="Software Engineering Intern (Apprenticeship)",
        location="San Francisco",
        remote=True,
        source_ats="usajobs",
        skills=["python", "sql"],
        visa_friendly=True,
        offers_sponsorship=True,
        employer_response_signal={
            "n": 200, "median_first_response_days": 3,
            "confidence": "high",
        },
        posted_at=TODAY,
        close_date=TODAY,
        required_certifications=["aws_saa", "gcp_ace"],
    )
    lanes = render_all(ctx, [op])
    for lane in lanes:
        for m in lane.matches:
            assert m.job_id != "j_bad", (
                f"Stage-1-failed job leaked into lane {lane.lane_id!r}"
            )


def test_missing_stage1_outcomes_is_conservatively_excluded():
    """fail-CLOSED rail: a row without a `stage1_outcomes` dict is
    treated as unqualified. This mirrors the Batch 4 rule that no
    byte leaves the pod without a policy allow — no row leaves
    Stage 1 without an outcome."""
    ctx = _ctx()
    op = {
        "job_id": "j_unqual", "title": "Python Engineer",
        "skills": ["python"], "remote": True, "posted_at": TODAY,
    }
    lanes = render_all(ctx, [op])
    for lane in lanes:
        for m in lane.matches:
            assert m.job_id != "j_unqual"


# =====================================================================
# 3. Fastest Credible Response — never a guarantee, n-gated
# =====================================================================
def test_fastest_credible_below_n_is_empty_with_reason():
    ctx = _ctx()
    op = _opp(
        "j1",
        employer_response_signal={
            "n": 5, "median_first_response_days": 2,
            "confidence": "low",
        },
    )
    lanes = {l.lane_id: l for l in render_all(ctx, [op])}
    fcr = lanes["fastest_credible_response"]
    assert fcr.empty_state is True
    assert fcr.empty_reason == "insufficient_n"


def test_fastest_credible_at_n_threshold_renders_with_confidence():
    ctx = _ctx()
    # Need >= 20 rows to hit min_n_for_public_render=20.
    rows = [
        _opp(
            f"j{i}",
            employer_response_signal={
                "n": 100, "median_first_response_days": 4,
                "confidence": "high",
            },
        )
        for i in range(25)
    ]
    lanes = {l.lane_id: l for l in render_all(ctx, rows)}
    fcr = lanes["fastest_credible_response"]
    assert fcr.empty_state is False
    assert fcr.requires_confidence_display is True
    for m in fcr.matches:
        assert m.reason["n"] == 100
        assert "confidence" in m.reason
        assert m.reason["note"] == "not_a_guarantee"


# =====================================================================
# 4. Missing lawful source → honest empty
# =====================================================================
def test_no_lawful_source_lane_renders_honest_empty():
    """Fabricate a spec with `lawful_source_available=False` and
    verify the render envelope."""
    from domains.lanes.registry import LaneSpec

    def _selector(ctx, opps):
        return [LaneMatch(job_id="should_not_appear",
                          reason={"why": "test"})]

    fake_spec = LaneSpec(
        id="income_now_placeholder",
        title="Income Now",
        description="Stub.",
        min_n_for_public_render=1,
        lawful_source_available=False,
        reason_schema=("why",),
        selector=_selector,
    )
    result = render_lane(fake_spec, _ctx(), [_opp("j1")])
    assert result.empty_state is True
    assert result.empty_reason == "no_lawful_source_yet"
    assert result.matches == ()


# =====================================================================
# 5. Reason drift lock — every match's reason keys ⊂ declared schema
# =====================================================================
def test_every_match_reason_keys_are_declared_in_schema():
    """A drift lock: if a selector emits a `reason` key not in the
    lane's `reason_schema`, the ATLAS auto-generated pages would
    show unexplained fields. Fail here BEFORE that happens."""
    ctx = _ctx()
    # A row that qualifies for as many lanes as possible.
    op = _opp(
        "j_multi",
        title="Software Engineering Intern",
        location="San Francisco",
        remote=True,
        source_ats="usajobs",
        skills=["python", "sql"],
        visa_friendly=True,
        offers_sponsorship=True,
        employer_response_signal={
            "n": 200, "median_first_response_days": 3,
            "confidence": "high",
        },
        posted_at=TODAY,
        close_date=TODAY,
        required_certifications=["aws_saa", "gcp_ace"],
        employer_sponsorship_history={
            "approved_petitions_last_year": 12,
            "source": "public_disclosure",
        },
    )
    # Need >= 20 rows for FCR to render. Duplicate to satisfy that
    # lane while keeping the multi-lane variety in the first row.
    rows = [op] + [
        _opp(
            f"j{i}",
            employer_response_signal={
                "n": 100, "median_first_response_days": 4,
                "confidence": "high",
            },
        )
        for i in range(25)
    ]
    lanes = render_all(ctx, rows)
    for lane in lanes:
        allowed = set(lane.reason_schema)
        for m in lane.matches:
            extras = set(m.reason.keys()) - allowed
            assert not extras, (
                f"lane {lane.lane_id!r} emitted reason key(s) "
                f"{extras} not in declared schema {allowed}"
            )


# =====================================================================
# 6. Selector determinism
# =====================================================================
def test_selectors_are_deterministic():
    ctx = _ctx()
    op = _opp("j1", skills=["python"], remote=True, posted_at=TODAY)
    r1 = render_all(ctx, [op])
    r2 = render_all(ctx, [op])
    assert [x.to_dict() for x in r1] == [x.to_dict() for x in r2]


# =====================================================================
# 7. Best Fit — skill overlap surfaces on the match
# =====================================================================
def test_best_fit_surfaces_skill_overlap():
    ctx = _ctx(approved_skill_names=frozenset({"python"}))
    op = _opp("j1", skills=["python", "airflow"])
    lanes = {l.lane_id: l for l in render_all(ctx, [op])}
    bf = lanes["best_fit"]
    assert not bf.empty_state
    assert bf.matches[0].reason == {
        "overlap_skills": ["python"], "n_overlap": 1,
    }


# =====================================================================
# 8. One Credential Away — exactly one missing cert
# =====================================================================
def test_one_credential_away_exact_gap():
    ctx = _ctx(approved_certifications=frozenset({"aws_saa"}))
    op = _opp("j1", required_certifications=["aws_saa", "gcp_ace"])
    lanes = {l.lane_id: l for l in render_all(ctx, [op])}
    lane = lanes["one_credential_away"]
    assert not lane.empty_state
    assert lane.matches[0].reason == {"missing_credential": "gcp_ace"}


def test_one_credential_away_requires_gap_of_exactly_one():
    ctx = _ctx(approved_certifications=frozenset())
    op = _opp("j1", required_certifications=["a", "b"])  # gap == 2
    lanes = {l.lane_id: l for l in render_all(ctx, [op])}
    lane = lanes["one_credential_away"]
    assert lane.empty_state

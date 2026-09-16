"""FYND ATLAS Fastest-Path Engine.

Given a set of qualified opportunities (each already Stage-1-cleared
by the Matching Constitution and route-resolved by the Route Engine)
plus a candidate's authorization/time budget, the Fastest-Path Engine
returns the single BEST-NEXT-ACTION ranked by:

  * expected_value       — a bounded, dimensionless score derived
                           from the constitution's Stage 2 signals.
                           NOT a fabricated probability.
  * urgency              — decays inversely with time-to-close where
                           a close date exists; silent otherwise.
  * time_cost            — inversely proportional to the route's
                           automation level (higher automation = less
                           candidate time).
  * liveness             — the liveness signal count from Batch 4.
  * confidence           — deterministic confidence tier derived from
                           evidence density; label, not a probability.
  * reversibility        — routes with candidate-controlled sends
                           (email, referral, manual web form) are
                           more reversible than automated ATS
                           submissions.
  * risk                 — hard-coded penalty for routes with known
                           accuracy locks (structured form ATS below
                           the form-map lock) or unpermitted
                           submission (no_apply_path).

Rails encoded in this module:

  * NO FABRICATED PROBABILITIES. Every score is bounded to a
    documented range with a discrete label; no "82.4% likely" output.
  * NO PROTECTED ATTRIBUTES anywhere in the input contract.
  * EVERY ACTION EXPLAINED. The returned `NextAction` carries a full
    factor breakdown that mirrors the ConstitutionResult's evidence
    shape: (positive, negative, unknown, what_would_change_it).
  * NO_APPLY_PATH is skipped from ranking. Preparation is still
    returned as an informational NextAction with
    `action_kind="prepare_only"` when nothing else qualifies.

The engine is pure — it does NOT read the database. Callers assemble
the input records from the runtime (services/gate_engine.py,
domains/liveness, etc.) and hand them in. This keeps testing trivial
and prevents the engine from leaking hidden state that could bias
rankings invisibly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from domains.applications.routes import (
    AutomationLevel,
    RouteType,
    resolve_route,
)


class ActionKind(str, Enum):
    """The kind of next action the engine returns.

    * `submit`        — proceed to submission via the resolved route.
    * `authorize`     — collect the per-application authorization or
                        candidate confirmation first, then submit.
    * `prepare_only`  — NO_APPLY_PATH; the engine will not send.
    """
    SUBMIT       = "submit"
    AUTHORIZE    = "authorize"
    PREPARE_ONLY = "prepare_only"


class ConfidenceTier(str, Enum):
    """Discrete confidence labels. NEVER a probability — a bounded
    label the UI can render truthfully."""
    HIGH  = "high"
    MED   = "med"
    LOW   = "low"


# ==================================================================
# Bounded factor score. All numeric contributions live on the same
# [0.0, 1.0] scale; the engine sums them with declared weights. The
# CANDIDATE never sees these numbers directly — they compose an
# ordering, not a claim.
# ==================================================================
FACTOR_WEIGHTS: dict[str, float] = {
    "expected_value":  0.30,
    "urgency":         0.15,
    "time_cost":       0.15,
    "liveness":        0.20,
    "reversibility":   0.10,
    "risk_penalty":    0.10,  # subtracted
}


@dataclass(frozen=True)
class Candidate:
    """Minimal candidate context. No protected attributes."""
    user_id: str
    time_budget_minutes: int | None = None
    authorized_job_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class OpportunityInput:
    """The engine's input row per opportunity.

    All fields are OPTIONAL beyond `job_id` + the opportunity dict
    itself. Silence is first-class — a missing `close_date`, missing
    `liveness_signal_count`, or missing `expected_value` yields a
    silent factor, never a fabricated value."""
    job_id: str
    opportunity: dict[str, Any]
    liveness_signal_count: int | None = None
    expected_value_hint: float | None = None
    close_date_days_out: int | None = None


@dataclass(frozen=True)
class NextAction:
    """The engine's output — one row per opportunity, ranked."""
    job_id: str
    action_kind: ActionKind
    route_type: RouteType
    score: float
    confidence: ConfidenceTier
    factors: dict[str, float]
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    unknown: tuple[str, ...]
    what_would_change_it: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id":               self.job_id,
            "action_kind":          self.action_kind.value,
            "route_type":           self.route_type.value,
            "score":                round(self.score, 6),
            "confidence":           self.confidence.value,
            "factors":              {k: round(v, 6) for k, v in self.factors.items()},
            "positive":             list(self.positive),
            "negative":             list(self.negative),
            "unknown":              list(self.unknown),
            "what_would_change_it": list(self.what_would_change_it),
        }


# ==================================================================
# Factor extraction — every extractor returns None when evidence is
# missing. `_compose_score` treats None as a silent zero contribution
# to the WEIGHTED sum but records it as `unknown` in the explanation.
# ==================================================================
def _factor_expected_value(inp: OpportunityInput) -> float | None:
    v = inp.expected_value_hint
    if v is None:
        return None
    return max(0.0, min(1.0, float(v)))


def _factor_urgency(inp: OpportunityInput) -> float | None:
    d = inp.close_date_days_out
    if d is None:
        return None
    if d <= 0:
        return 0.0  # already closed — no urgency contribution
    if d <= 3:
        return 1.0
    if d <= 7:
        return 0.7
    if d <= 30:
        return 0.4
    return 0.1


_TIME_COST_BY_AUTOMATION: dict[AutomationLevel, float] = {
    AutomationLevel.AUTOMATED:   1.0,
    AutomationLevel.ASSISTED:    0.7,
    AutomationLevel.MANUAL:      0.35,
    AutomationLevel.UNPERMITTED: 0.0,
}


def _factor_time_cost(automation: AutomationLevel) -> float:
    """Higher automation → lower time cost → higher factor value.
    Bounded and enumerated; the caller sees the label, not a magic
    number."""
    return _TIME_COST_BY_AUTOMATION[automation]


def _factor_liveness(inp: OpportunityInput) -> float | None:
    n = inp.liveness_signal_count
    if n is None:
        return None
    if n <= 0:
        return 0.0
    if n == 1:
        return 0.4
    if n == 2:
        return 0.75
    return 1.0


_REVERSIBILITY_BY_ROUTE: dict[RouteType, float] = {
    RouteType.DIRECT_ATS_API:        0.3,  # once submitted, harder to withdraw silently
    RouteType.STRUCTURED_ATS_FORM:   0.5,
    RouteType.UNSTRUCTURED_WEB_FORM: 0.85,
    RouteType.EMAIL_SUBMISSION:      0.9,
    RouteType.FEDERAL_PORTAL:        0.6,
    RouteType.PARTNER_REFERRAL:      0.7,
    RouteType.NO_APPLY_PATH:         1.0,   # not submitted at all
}


_RISK_BY_ROUTE: dict[RouteType, float] = {
    # Accuracy lock: structured form ATS below the >99% form-map
    # accuracy gate is elevated risk today (assisted, not automated).
    RouteType.STRUCTURED_ATS_FORM:   0.5,
    RouteType.UNSTRUCTURED_WEB_FORM: 0.4,
    RouteType.EMAIL_SUBMISSION:      0.3,
    RouteType.FEDERAL_PORTAL:        0.3,
    # Direct ATS API is the most-vetted path.
    RouteType.DIRECT_ATS_API:        0.15,
    RouteType.PARTNER_REFERRAL:      0.2,
    # NO_APPLY_PATH cannot submit at all — treated as full-risk to
    # ensure it never wins the ranking, but paired with SUBMIT-
    # blocked action_kind so nothing sends.
    RouteType.NO_APPLY_PATH:         1.0,
}


# ==================================================================
# Score composition
# ==================================================================
def _compose_score(factors_present: dict[str, float]) -> float:
    """Weighted sum of PRESENT factors, minus the weighted risk
    penalty. Absent factors contribute nothing (silent). No
    fabricated missing values."""
    total = 0.0
    total_weight = 0.0
    for key, w in FACTOR_WEIGHTS.items():
        if key == "risk_penalty":
            continue
        val = factors_present.get(key)
        if val is None:
            continue
        total += val * w
        total_weight += w
    # Normalize so a partly-informed opportunity is not falsely dragged
    # down purely because factors are silent.
    base = (total / total_weight) if total_weight > 0 else 0.0
    risk = factors_present.get("risk_penalty") or 0.0
    return max(0.0, min(1.0, base - risk * FACTOR_WEIGHTS["risk_penalty"]))


def _confidence_from_factors(factors_present: dict[str, float]) -> ConfidenceTier:
    """Confidence tier is a LABEL, not a probability. Based on how
    many non-None factors informed the score."""
    n_informed = sum(1 for k, v in factors_present.items()
                     if k != "risk_penalty" and v is not None)
    if n_informed >= 4:
        return ConfidenceTier.HIGH
    if n_informed >= 2:
        return ConfidenceTier.MED
    return ConfidenceTier.LOW


def _explanations(inp: OpportunityInput,
                  factors: dict[str, float | None],
                  route_type: RouteType,
                  ) -> tuple[tuple[str, ...], tuple[str, ...],
                             tuple[str, ...], tuple[str, ...]]:
    """Return (positive, negative, unknown, what_would_change_it).
    Every entry is a stable machine-readable label so the UI never
    has to parse prose."""
    positive: list[str] = [f"route:{route_type.value}"]
    negative: list[str] = []
    unknown: list[str] = []
    change: list[str] = []
    for key, val in factors.items():
        if val is None:
            unknown.append(f"factor:{key}")
            if key == "urgency":
                change.append("Employer publishes a close date.")
            elif key == "liveness":
                change.append("Additional liveness signals arrive.")
            elif key == "expected_value":
                change.append(
                    "Candidate adds approved skills that match the "
                    "posting."
                )
        elif key == "risk_penalty" and val > 0.5:
            negative.append(f"factor:{key}")
        else:
            positive.append(f"factor:{key}")
    return tuple(positive), tuple(negative), tuple(unknown), tuple(change)


# ==================================================================
# Public API
# ==================================================================
def rank(
    candidate: Candidate,
    opportunities: list[OpportunityInput],
) -> list[NextAction]:
    """Rank opportunities by the composite score, DESCENDING. Every
    row returns a NextAction with a full explanation payload."""
    out: list[NextAction] = []
    for inp in opportunities:
        route_spec = resolve_route(inp.opportunity)
        route_type = route_spec.type

        factors_optional: dict[str, float | None] = {
            "expected_value": _factor_expected_value(inp),
            "urgency":        _factor_urgency(inp),
            "time_cost":      _factor_time_cost(route_spec.automation_level),
            "liveness":       _factor_liveness(inp),
            "reversibility":  _REVERSIBILITY_BY_ROUTE[route_type],
            "risk_penalty":   _RISK_BY_ROUTE[route_type],
        }
        factors_present = {k: v for k, v in factors_optional.items()
                           if v is not None}

        score = _compose_score(factors_present)
        confidence = _confidence_from_factors(factors_optional)

        # ActionKind resolution:
        if not route_spec.submission_permitted:
            action = ActionKind.PREPARE_ONLY
        elif inp.job_id not in candidate.authorized_job_ids:
            action = ActionKind.AUTHORIZE
        else:
            action = ActionKind.SUBMIT

        positive, negative, unknown, change = _explanations(
            inp, factors_optional, route_type,
        )

        out.append(NextAction(
            job_id=inp.job_id,
            action_kind=action,
            route_type=route_type,
            score=score,
            confidence=confidence,
            factors={k: (v if v is not None else 0.0)
                     for k, v in factors_optional.items()},
            positive=positive,
            negative=negative,
            unknown=unknown,
            what_would_change_it=change,
        ))

    # Sort: PREPARE_ONLY (submission-restricted) ALWAYS sorts after
    # every submittable action — structural rail, not a score
    # tiebreaker. Within each bucket: primary DESC by score; then
    # SUBMIT before AUTHORIZE; then stable by job_id for determinism.
    def _sort_key(a: NextAction) -> tuple[int, float, int, str]:
        is_prepare_only = 1 if a.action_kind is ActionKind.PREPARE_ONLY else 0
        action_rank = {
            ActionKind.SUBMIT: 0,
            ActionKind.AUTHORIZE: 1,
            ActionKind.PREPARE_ONLY: 2,
        }[a.action_kind]
        return (is_prepare_only, -a.score, action_rank, a.job_id)

    out.sort(key=_sort_key)
    return out


def best_next(candidate: Candidate,
              opportunities: list[OpportunityInput]) -> NextAction | None:
    """Convenience — return only the top-ranked NextAction, or None
    when the input list is empty."""
    ranked = rank(candidate, opportunities)
    return ranked[0] if ranked else None

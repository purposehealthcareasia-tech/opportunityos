"""Stage 2 ranking signals registry — DECLARATIVE.

Ranking signals refine ORDER among opportunities that have already
cleared Stage 1. They MUST NOT:

  * import from `matching.gates` — enforced by the architectural test
    `test_ranking_module_does_not_import_gates`.
  * carry any protected attribute (race, gender, age, national origin,
    religion, marital/parental status, disability, sexual orientation,
    veteran status). Attempting to encode one is a review-time reject
    and would trip the ATLAS truth surface.
  * apply auto-penalty for missing data (a `null` evidence value
    yields a `null` contribution, not a negative one).
  * fabricate a probability. Every signal carries a discrete
    `direction` and a bounded, dimensionless `weight_range`; the
    evaluator combines them by ordered priority, not by inventing
    calibrated numbers we cannot back with data.

The `/standards/matching-constitution` public page renders this
registry directly, so any change ships to the page automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final


class SignalDirection(str, Enum):
    """A ranking signal contributes in ONE direction. `positive` means
    higher-is-better; `negative` means lower-is-better; `neutral`
    means the signal informs the explanation but does not shift
    order."""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class RankingSignalSpec:
    """Declarative spec for a Stage 2 ranking signal.

    Fields mirror `GateSpec` intentionally so the constitution page
    can render both tables the same way.
    """
    id: str
    description: str
    direction: SignalDirection
    evidence: tuple[str, ...]
    what_would_change_it: tuple[str, ...] = field(default_factory=tuple)


_R_LIVENESS_CONFIDENCE = RankingSignalSpec(
    id="liveness_confidence",
    description=(
        "How recently and how many independent times the posting has "
        "been observed as live. Higher confidence ranks higher."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=(
        "job.liveness_signals[]",
        "job.last_verified_at",
    ),
    what_would_change_it=(
        "The posting is re-verified from an additional source.",
    ),
)

_R_SKILL_OVERLAP_APPROVED = RankingSignalSpec(
    id="skill_overlap_approved",
    description=(
        "Count of approved candidate skill claims that intersect the "
        "posting's stated skills. Non-approved claims do not count."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=(
        "candidate.claims(type=skill,status=approved)",
        "job.skills",
    ),
    what_would_change_it=(
        "The candidate adds an approved skill claim that matches.",
        "The employer updates the posting's required skills.",
    ),
)

_R_ROUTE_AUTOMATION = RankingSignalSpec(
    id="route_automation_level",
    description=(
        "How autonomously the platform can act on the opportunity's "
        "route (see route_engine). Higher automation ranks higher "
        "because the candidate's expected time-to-submit is lower."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=(
        "job.route_type",
        "route_engine.automation_level",
    ),
    what_would_change_it=(
        "The employer moves the posting to a more submission-friendly "
        "route.",
    ),
)

_R_URGENCY = RankingSignalSpec(
    id="urgency_expiring_soon",
    description=(
        "The posting has an announced close date and it is inside a "
        "narrow horizon. Absent a close date, this signal is silent "
        "(no fabricated urgency)."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=(
        "job.close_date",
        "job.posted_at",
    ),
    what_would_change_it=(
        "The employer publishes a close date.",
        "The posting is renewed / reposted.",
    ),
)

_R_LOCATION_FIT = RankingSignalSpec(
    id="location_fit_soft",
    description=(
        "Distance from the candidate's declared home locations, or "
        "match of remote preference. Only counted when the "
        "candidate has declared locations; otherwise silent."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=(
        "candidate.preferences.locations",
        "job.location",
        "job.remote",
    ),
    what_would_change_it=(
        "The candidate updates their preferred locations.",
    ),
)

_R_SALARY_DELTA = RankingSignalSpec(
    id="salary_vs_floor_delta",
    description=(
        "How much the posted comp range exceeds the candidate's "
        "declared floor. Silent when the posting has no comp range "
        "or the candidate has no floor."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=(
        "job.compensation",
        "candidate.preferences.salary_floor",
    ),
    what_would_change_it=(
        "The employer publishes a comp range.",
        "The candidate updates their floor.",
    ),
)

_R_COUNTRY_ALLOWLIST_MATCH = RankingSignalSpec(
    id="country_allowlist_match",
    description=(
        "The candidate's home country is on the posting's structured "
        "country_allowlist. Absent a structured allowlist, this "
        "signal is silent (indeterminate)."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=(
        "job.country_allowlist",
        "candidate.location.country",
    ),
    what_would_change_it=(
        "The employer publishes a structured country_allowlist.",
        "The candidate updates their home country.",
    ),
)

_R_EMPLOYER_QUALITY = RankingSignalSpec(
    id="employer_data_honesty",
    description=(
        "The employer's Data-Honesty Score (spec-only backlog item). "
        "A structural placeholder: renders `null` until the scoring "
        "surface ships. Included in the registry so the "
        "constitution page shows the roadmap honestly."
    ),
    direction=SignalDirection.POSITIVE,
    evidence=("employer.data_honesty_score",),
    what_would_change_it=(
        "The Data-Honesty scoring surface ships (roadmap item).",
    ),
)


RANKING_REGISTRY: Final[tuple[RankingSignalSpec, ...]] = (
    _R_LIVENESS_CONFIDENCE,
    _R_SKILL_OVERLAP_APPROVED,
    _R_ROUTE_AUTOMATION,
    _R_URGENCY,
    _R_LOCATION_FIT,
    _R_SALARY_DELTA,
    _R_COUNTRY_ALLOWLIST_MATCH,
    _R_EMPLOYER_QUALITY,
)


def by_id(signal_id: str) -> RankingSignalSpec | None:
    for s in RANKING_REGISTRY:
        if s.id == signal_id:
            return s
    return None

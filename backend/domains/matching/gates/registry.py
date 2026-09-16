"""Stage 1 gates registry — DECLARATIVE.

Every gate that Stage 1 may run is registered here. The registry is:

  * INTROSPECTABLE — the `/standards/matching-constitution` page can
    render the current gate set directly from `GATE_REGISTRY` at
    request time, so the page cannot drift from the code.
  * ORDERED — gates are evaluated in the declared order; the first
    `fail` short-circuits the group.
  * DEGREE-BLIND — `education_requirement` and `experience_band`
    exist in the runtime `services/gate_engine.py` but they always
    surface as NOTE-on-pass; they are declared here with
    `is_hard_exclusion=False` to make that explicit.
  * DISJOINT FROM RANKING — no ranking signal is allowed to appear
    here, and no gate is allowed to appear in `ranking/registry.py`.
    The disjointness invariant is asserted by
    `test_matching_constitution.py`.

Only THREE gate families may hard-exclude (per Founder Directive #3):
  (a) work authorization
  (b) legally mandatory licensure
  (c) geographic impossibility

Every other gate emits `pass` + `note` on a mismatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from domains.matching.gates.outcomes import GateOutcome


@dataclass(frozen=True)
class GateSpec:
    """Declarative spec for a Stage 1 gate.

    Fields:
      * `id`                    unique kebab-case identifier.
      * `family`                which of the four ATLAS families the
                                gate belongs to (`work_authorization`,
                                `licensure`, `geography`, `note_only`).
      * `description`           one-line human summary rendered on
                                the public Constitution page.
      * `is_hard_exclusion`     True IFF a `fail` here removes the
                                opportunity from Stage 2 entirely.
                                False for note-only gates.
      * `possible_outcomes`     the subset of `GateOutcome` this gate
                                can emit. Encoded so the constitution
                                page can render 'this gate cannot
                                return X' truthfully.
      * `required_evidence`     structured evidence keys the gate
                                reads (never protected attributes).
      * `what_would_change_it`  human-readable list of "the outcome
                                would change if...".
    """
    id: str
    family: str
    description: str
    is_hard_exclusion: bool
    possible_outcomes: tuple[GateOutcome, ...]
    required_evidence: tuple[str, ...]
    what_would_change_it: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------
# Hard-exclusion gates — the ONLY three families that can `fail`.
# --------------------------------------------------------------------
_G_VACANCY_OPEN = GateSpec(
    id="vacancy_open",
    family="liveness",
    description=(
        "The posting is currently live and has been re-verified within "
        "the freshness window."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(GateOutcome.PASS, GateOutcome.FAIL,
                       GateOutcome.UNKNOWN),
    required_evidence=("job.status", "job.last_verified_at"),
    what_would_change_it=(
        "The employer re-verifies the posting.",
        "The freshness window is reconfigured.",
    ),
)

_G_DUPLICATE = GateSpec(
    id="duplicate_check",
    family="submission_integrity",
    description=(
        "The candidate has no existing non-closed application for this "
        "opportunity."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(GateOutcome.PASS, GateOutcome.FAIL),
    required_evidence=("applications.by(user_id,job_id)",),
    what_would_change_it=(
        "The candidate withdraws or the existing application closes.",
    ),
)

_G_WORK_AUTH = GateSpec(
    id="work_auth",
    family="work_authorization",
    description=(
        "The candidate's declared work-authorization status is "
        "accepted by the opportunity's posted allowlist."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS, GateOutcome.FAIL,
        GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    ),
    required_evidence=(
        "candidate.work_auth_status",
        "job.eligibility_requirements.accepted_statuses",
    ),
    what_would_change_it=(
        "The candidate confirms their work-auth status.",
        "The posting's accepted-statuses list changes.",
    ),
)

_G_SPONSORSHIP = GateSpec(
    id="sponsorship",
    family="work_authorization",
    description=(
        "If the candidate needs sponsorship, the employer offers "
        "sponsorship for this opportunity."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS, GateOutcome.FAIL,
        GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    ),
    required_evidence=(
        "candidate.needs_sponsorship",
        "job.offers_sponsorship",
    ),
    what_would_change_it=(
        "The candidate updates their sponsorship-need status.",
        "The employer updates their sponsorship policy for this role.",
    ),
)

_G_ITAR = GateSpec(
    id="itar",
    family="work_authorization",
    description=(
        "For roles subject to ITAR / US-person requirement, the "
        "candidate is a US person."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS, GateOutcome.FAIL,
        GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    ),
    required_evidence=(
        "job.requires_us_person",
        "candidate.work_auth_status",
    ),
    what_would_change_it=(
        "The candidate confirms a US-person work-auth status.",
    ),
)

_G_STEM_OPT = GateSpec(
    id="stem_opt_viability",
    family="work_authorization",
    description=(
        "For STEM-OPT / E-Verify sensitive candidates, the plausible "
        "start date falls inside the candidate's authorization window."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS, GateOutcome.FAIL,
        GateOutcome.UNKNOWN,
        GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    ),
    required_evidence=(
        "candidate.opt_window",
        "job.expected_start",
    ),
    what_would_change_it=(
        "The candidate submits an updated OPT window.",
        "The employer clarifies expected start.",
    ),
)

_G_SECURITY_CLEARANCE = GateSpec(
    id="security_clearance",
    family="work_authorization",
    description=(
        "If the role requires an active security clearance, the "
        "candidate holds an equivalent or higher clearance."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS, GateOutcome.FAIL,
        GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    ),
    required_evidence=(
        "job.required_clearance",
        "candidate.clearances",
    ),
    what_would_change_it=(
        "The candidate confirms a matching clearance in their claims.",
    ),
)

_G_LICENSURE = GateSpec(
    id="licensure",
    family="licensure",
    description=(
        "For roles legally requiring a specific license or "
        "certification, the candidate holds a precise match."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS, GateOutcome.FAIL,
        GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    ),
    required_evidence=(
        "job.required_licenses",
        "candidate.certifications",
    ),
    what_would_change_it=(
        "The candidate adds a matching certification claim.",
    ),
)

_G_LOCATION_ONSITE = GateSpec(
    id="location_onsite",
    family="geography",
    description=(
        "For strictly on-site roles, the opportunity's geography "
        "intersects the candidate's declared locations or remote "
        "preferences."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS, GateOutcome.FAIL,
        GateOutcome.UNKNOWN,
    ),
    required_evidence=(
        "job.location",
        "job.remote",
        "candidate.preferences.locations",
        "candidate.preferences.remote_ok",
    ),
    what_would_change_it=(
        "The candidate widens their locations or enables remote-ok.",
        "The employer relaxes the on-site requirement.",
    ),
)

_G_AUTHORIZATION_SCOPE = GateSpec(
    id="authorization_scope",
    family="submission_integrity",
    description=(
        "The candidate has authorized platform-side submission for "
        "this opportunity (per-application authorization; enforced at "
        "submit-time)."
    ),
    is_hard_exclusion=True,
    possible_outcomes=(
        GateOutcome.PASS,
        GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    ),
    required_evidence=("authorizations.by(user_id,job_id)",),
    what_would_change_it=(
        "The candidate grants submission authorization.",
    ),
)


# --------------------------------------------------------------------
# NOTE-ONLY gates — surface a visible NOTE on `pass`, never `fail`.
# --------------------------------------------------------------------
_G_EXPERIENCE_BAND = GateSpec(
    id="experience_band",
    family="note_only",
    description=(
        "The candidate's approved employment years compared to the "
        "role's stated years_min. Degree-blind principle: NEVER hard-"
        "excludes; emits a NOTE if mismatched."
    ),
    is_hard_exclusion=False,
    possible_outcomes=(GateOutcome.PASS,),
    required_evidence=(
        "candidate.employment.years",
        "job.years_min",
    ),
    what_would_change_it=(
        "The candidate adds employment history claims.",
    ),
)

_G_EDUCATION_REQUIREMENT = GateSpec(
    id="education_requirement",
    family="note_only",
    description=(
        "The candidate's approved education level vs. the role's "
        "declared degree_level. Degree-blind principle: NEVER hard-"
        "excludes; emits a NOTE."
    ),
    is_hard_exclusion=False,
    possible_outcomes=(GateOutcome.PASS,),
    required_evidence=(
        "candidate.education.level",
        "job.degree_level",
    ),
    what_would_change_it=(
        "The candidate adds an education claim.",
    ),
)

_G_SALARY_FLOOR = GateSpec(
    id="salary_floor",
    family="note_only",
    description=(
        "The candidate's declared salary floor vs. the posting's "
        "compensation range. Emits a NOTE on mismatch; never blocks."
    ),
    is_hard_exclusion=False,
    possible_outcomes=(GateOutcome.PASS,),
    required_evidence=(
        "candidate.preferences.salary_floor",
        "job.compensation",
    ),
    what_would_change_it=(
        "The candidate lowers their floor or the posting raises comp.",
    ),
)

_G_EMPLOYER_EXCLUSIONS = GateSpec(
    id="employer_exclusions",
    family="note_only",
    description=(
        "The employer's domain is not on the candidate's exclusion "
        "list. On match the opportunity is hidden from the feed (via "
        "hidden_jobs), but this gate emits a NOTE rather than a fail."
    ),
    is_hard_exclusion=False,
    possible_outcomes=(GateOutcome.PASS,),
    required_evidence=(
        "candidate.exclude_employers",
        "job.employer_domain",
    ),
    what_would_change_it=(
        "The candidate removes the employer from their exclusion list.",
    ),
)


# --------------------------------------------------------------------
# Registry — declaration order == evaluation order.
# --------------------------------------------------------------------
GATE_REGISTRY: Final[tuple[GateSpec, ...]] = (
    # Liveness & submission integrity first (cheapest reads).
    _G_VACANCY_OPEN,
    _G_AUTHORIZATION_SCOPE,
    _G_DUPLICATE,
    # Work authorization family.
    _G_WORK_AUTH,
    _G_SPONSORSHIP,
    _G_STEM_OPT,
    _G_ITAR,
    _G_SECURITY_CLEARANCE,
    # Licensure.
    _G_LICENSURE,
    # Geography.
    _G_LOCATION_ONSITE,
    # Note-only.
    _G_EXPERIENCE_BAND,
    _G_EDUCATION_REQUIREMENT,
    _G_SALARY_FLOOR,
    _G_EMPLOYER_EXCLUSIONS,
)


HARD_EXCLUSION_FAMILIES: Final[frozenset[str]] = frozenset({
    "work_authorization", "licensure", "geography",
    # `liveness` + `submission_integrity` short-circuit before Stage 2
    # even though they are not on the ATLAS "may hard-exclude" list —
    # they protect the platform, not the eligibility surface.
    "liveness", "submission_integrity",
})


def by_id(gate_id: str) -> GateSpec | None:
    """Case-sensitive lookup. Returns None if unknown."""
    for g in GATE_REGISTRY:
        if g.id == gate_id:
            return g
    return None

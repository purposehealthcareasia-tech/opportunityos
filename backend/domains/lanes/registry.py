"""FYND ATLAS Lanes registry.

A lane is a candidate-facing view over the qualified opportunity
set. The ATLAS mandates:

  * Every lane exposes its selection logic (machine-readable "why
    this lane contains this job").
  * Lanes consume Stage 1 gate outcomes from the Matching
    Constitution. A Stage-1-failed job cannot appear in ANY lane —
    invariant asserted by tests.
  * Lanes with no lawful source or insufficient `n` render an
    HONEST EMPTY state (never a fabricated set).
  * "Fastest Credible Response" only ships when `n` is sufficient
    AND privacy-safe AND confidence is shown; NEVER a guarantee.

The 13 lanes (declaration order == UI ordering):
  1. Best Fit
  2. Fastest Credible Response
  3. Local Now
  4. Remote Worldwide
  5. Visa-Friendly
  6. Sponsorship Possible
  7. New Today
  8. Closing Soon
  9. Government
 10. Internships
 11. Apprenticeships
 12. Outside My Usual Path
 13. One Credential Away

The `Income Now` lane exists in the ATLAS backlog but has no lawful
source today; it is DELIBERATELY not registered so no candidate can
see a lane that would be an empty promise. It ships only when a
lawful source connector exists.

Rails:
  * Every lane's `selector` is a PURE function: (LaneContext, list of
    opportunities) → list of (opportunity, lane_reason_dict). No IO.
    Reasoning is deterministic + explainable per row.
  * Every lane declares its `min_n` for public rendering. Below that,
    the lane surfaces an empty state with `reason: "insufficient_n"`
    (never fabricated).
  * Lanes NEVER read protected attributes. Enforced by the same
    AST-scan machinery used for the constitution registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Final


# =====================================================================
# Types
# =====================================================================
@dataclass(frozen=True)
class LaneContext:
    """Minimal candidate + platform context handed to every lane.

    Deliberately narrow — a lane must never read from the DB or
    invoke external services. Everything a lane needs comes from
    inputs the caller has already assembled. This keeps lanes
    deterministic, cheap to test, and impossible to leak PII from.
    """
    candidate_country: str | None = None
    candidate_locations: tuple[str, ...] = ()
    candidate_remote_ok: bool = False
    approved_skill_names: frozenset[str] = field(default_factory=frozenset)
    approved_certifications: frozenset[str] = field(default_factory=frozenset)
    needs_sponsorship: bool = False
    # `now_utc_iso` and `today_utc_iso` are injected so lanes are
    # deterministic in tests (no clock read inside the lane).
    now_utc_iso: str = ""
    today_utc_iso: str = ""


@dataclass(frozen=True)
class LaneMatch:
    """One (opportunity, lane_reason) pair emitted by a lane's
    selector. `lane_reason` is a small JSON-safe dict explaining WHY
    the opportunity is in the lane."""
    job_id: str
    reason: dict[str, Any]


LaneSelector = Callable[[LaneContext, list[dict]], list[LaneMatch]]


@dataclass(frozen=True)
class LaneSpec:
    """Declarative spec for one lane."""
    id: str
    title: str
    description: str
    min_n_for_public_render: int
    # If True, this lane is DISABLED (empty state) until a lawful
    # source connector exists. Used for Income Now and other lanes
    # whose lawful path is not present today.
    lawful_source_available: bool
    # Public "why this job in this lane?" — the selector must produce
    # a `reason` dict whose keys are a subset of this contract.
    reason_schema: tuple[str, ...]
    selector: LaneSelector
    # Confidence-shown flag — lanes that promise something about
    # employer behaviour (Fastest Credible Response) MUST surface
    # confidence + n on the response envelope.
    requires_confidence_display: bool = False


# =====================================================================
# Helpers used by multiple selectors
# =====================================================================
def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _country_from_row(op: dict) -> str | None:
    """Pull the primary country from an opportunity row's
    structured country_allowlist. If the row has no structured
    country, return None (never inferred)."""
    ca = op.get("country_allowlist")
    if isinstance(ca, list) and ca:
        return ca[0]
    return None


def _stage1_all_pass(op: dict) -> bool:
    """A job is eligible for ANY lane only if every Stage 1 gate
    resolved to `pass` (or `unknown` / `candidate_confirmation_
    required` on note-only lanes). A `fail` on any hard-exclusion
    gate REMOVES the row from every lane.

    The caller marks Stage 1 outcomes on the opportunity dict under
    `stage1_outcomes: {gate_id: outcome_str}`. If that key is
    missing, we conservatively treat the row as unqualified (never
    include it) — this preserves the fail-CLOSED rail from Batch 4.
    """
    outcomes = op.get("stage1_outcomes")
    if not isinstance(outcomes, dict) or not outcomes:
        return False
    return not any(v == "fail" for v in outcomes.values())


def _days_between_iso(a_iso: str, b_iso: str) -> int | None:
    """Compute integer days between two ISO datetimes. Returns None
    if either input cannot be parsed."""
    from datetime import datetime
    try:
        da = datetime.fromisoformat(a_iso.replace("Z", "+00:00"))
        db = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
        return (da.date() - db.date()).days
    except Exception:
        return None


# =====================================================================
# Selectors
# =====================================================================
def _select_best_fit(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows that (a) pass Stage 1 and (b) have at least one approved
    skill overlap. Reasoning: which skill(s) overlapped."""
    out: list[LaneMatch] = []
    if not ctx.approved_skill_names:
        return out
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        posted_skills = {
            _norm(s) for s in (op.get("skills") or [])
        }
        overlap = sorted(ctx.approved_skill_names & posted_skills)
        if not overlap:
            continue
        out.append(LaneMatch(
            job_id=op["job_id"],
            reason={"overlap_skills": overlap, "n_overlap": len(overlap)},
        ))
    return out


def _select_fastest_credible_response(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows for employers with a published median response signal AND
    sufficient n (`response_signal.n >= 20`). NEVER a guarantee —
    the response envelope carries the confidence + n so the UI
    surfaces it visibly.
    """
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        sig = op.get("employer_response_signal") or {}
        n = sig.get("n") or 0
        median_days = sig.get("median_first_response_days")
        confidence = sig.get("confidence")
        if n < 20 or median_days is None or confidence is None:
            continue
        out.append(LaneMatch(
            job_id=op["job_id"],
            reason={
                "median_first_response_days": median_days,
                "n": n,
                "confidence": confidence,
                "note": "not_a_guarantee",
            },
        ))
    return out


def _select_local_now(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows in one of the candidate's declared locations (case-
    insensitive substring), non-remote."""
    out: list[LaneMatch] = []
    cand_locs = {_norm(l) for l in ctx.candidate_locations if l}
    if not cand_locs:
        return out
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        if op.get("remote"):
            continue
        loc = _norm(op.get("location"))
        if not loc:
            continue
        matched = sorted(l for l in cand_locs if l in loc)
        if not matched:
            continue
        out.append(LaneMatch(
            job_id=op["job_id"],
            reason={"matched_location_terms": matched},
        ))
    return out


def _select_remote_worldwide(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows explicitly marked remote OR with a country_allowlist
    that includes a `remote` marker (some ATSes)."""
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        if not op.get("remote"):
            continue
        out.append(LaneMatch(
            job_id=op["job_id"],
            reason={"remote": True},
        ))
    return out


def _select_visa_friendly(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Employers with a public visa-friendly signal. Structured
    field `visa_friendly=True` OR a documented sponsorship history
    entry. Never inferred from title alone."""
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        if op.get("visa_friendly") is True:
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={"visa_friendly_declared": True},
            ))
            continue
        history = op.get("employer_sponsorship_history") or {}
        n_recent = history.get("approved_petitions_last_year") or 0
        if n_recent > 0:
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={
                    "sponsorship_history_last_year": n_recent,
                    "source": history.get("source"),
                },
            ))
    return out


def _select_sponsorship_possible(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows where the employer explicitly offers sponsorship for this
    role (`offers_sponsorship=True`). Distinct from visa-friendly:
    this is the specific opportunity's stated policy, not employer-
    wide history."""
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        if op.get("offers_sponsorship") is True:
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={"offers_sponsorship": True},
            ))
    return out


def _select_new_today(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows posted (or first observed) today per the caller's
    injected `today_utc_iso`."""
    out: list[LaneMatch] = []
    if not ctx.today_utc_iso:
        return out
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        posted = op.get("posted_at") or ""
        d = _days_between_iso(posted, ctx.today_utc_iso)
        if d is None:
            continue
        if d == 0:
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={"posted_at": posted, "days_ago": 0},
            ))
    return out


def _select_closing_soon(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows with a declared `close_date` within 7 days of now."""
    out: list[LaneMatch] = []
    if not ctx.today_utc_iso:
        return out
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        close = op.get("close_date")
        if not close:
            continue
        d = _days_between_iso(close, ctx.today_utc_iso)
        if d is None:
            continue
        if 0 <= d <= 7:
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={"close_date": close, "days_until_close": d},
            ))
    return out


def _select_government(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows sourced from federal / government portals (usajobs
    today; state/local extensible)."""
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        source = _norm(op.get("source_ats"))
        if source in {"usajobs"}:
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={"source_ats": source},
            ))
    return out


_INTERN_TITLE_TOKENS = frozenset({
    "intern", "internship", "co-op", "coop",
})


def _select_internships(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        title = _norm(op.get("title"))
        if any(tok in title for tok in _INTERN_TITLE_TOKENS):
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={"title_signal": "intern_or_coop"},
            ))
    return out


_APPRENTICE_TITLE_TOKENS = frozenset({
    "apprentice", "apprenticeship",
})


def _select_apprenticeships(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        title = _norm(op.get("title"))
        if any(tok in title for tok in _APPRENTICE_TITLE_TOKENS):
            out.append(LaneMatch(
                job_id=op["job_id"],
                reason={"title_signal": "apprenticeship"},
            ))
    return out


def _select_outside_usual_path(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows that Stage-1-pass but have NO overlap with the
    candidate's approved skills — an adjacency signal, not a
    downgrade."""
    out: list[LaneMatch] = []
    if not ctx.approved_skill_names:
        return out
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        posted_skills = {_norm(s) for s in (op.get("skills") or [])}
        if not posted_skills:
            continue
        if ctx.approved_skill_names & posted_skills:
            continue  # covered by Best Fit
        out.append(LaneMatch(
            job_id=op["job_id"],
            reason={
                "adjacent_reason": "no_skill_overlap_yet",
                "posted_skills_sample": sorted(posted_skills)[:5],
            },
        ))
    return out


def _select_one_credential_away(ctx: LaneContext, opps: list[dict]) -> list[LaneMatch]:
    """Rows requiring a specific certification the candidate does NOT
    currently hold, but where the gap is EXACTLY one credential. The
    posting's `required_certifications` list must have exactly one
    entry not in the candidate's approved set."""
    out: list[LaneMatch] = []
    for op in opps:
        if not _stage1_all_pass(op):
            continue
        req = {_norm(c) for c in (op.get("required_certifications") or [])}
        if not req:
            continue
        missing = req - ctx.approved_certifications
        if len(missing) != 1:
            continue
        out.append(LaneMatch(
            job_id=op["job_id"],
            reason={"missing_credential": sorted(missing)[0]},
        ))
    return out


# =====================================================================
# Registry
# =====================================================================
_L_BEST_FIT = LaneSpec(
    id="best_fit",
    title="Best Fit",
    description=(
        "Roles whose posted skills overlap with your approved skill "
        "claims."
    ),
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("overlap_skills", "n_overlap"),
    selector=_select_best_fit,
)

_L_FASTEST_CREDIBLE = LaneSpec(
    id="fastest_credible_response",
    title="Fastest Credible Response",
    description=(
        "Employers with a published median first-response time "
        "backed by at least 20 observations. Never a guarantee — "
        "confidence and sample size are shown."
    ),
    min_n_for_public_render=20,
    lawful_source_available=True,
    reason_schema=("median_first_response_days", "n", "confidence", "note"),
    selector=_select_fastest_credible_response,
    requires_confidence_display=True,
)

_L_LOCAL_NOW = LaneSpec(
    id="local_now",
    title="Local Now",
    description="On-site roles in your declared locations.",
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("matched_location_terms",),
    selector=_select_local_now,
)

_L_REMOTE_WORLDWIDE = LaneSpec(
    id="remote_worldwide",
    title="Remote Worldwide",
    description="Roles explicitly marked remote by the employer.",
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("remote",),
    selector=_select_remote_worldwide,
)

_L_VISA_FRIENDLY = LaneSpec(
    id="visa_friendly",
    title="Visa-Friendly",
    description=(
        "Employers with a declared visa-friendly signal or a "
        "documented sponsorship history for the last year."
    ),
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("visa_friendly_declared", "sponsorship_history_last_year", "source"),
    selector=_select_visa_friendly,
)

_L_SPONSORSHIP_POSSIBLE = LaneSpec(
    id="sponsorship_possible",
    title="Sponsorship Possible",
    description=(
        "Postings whose employer explicitly offers sponsorship for "
        "this role. Distinct from visa-friendly (employer-wide)."
    ),
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("offers_sponsorship",),
    selector=_select_sponsorship_possible,
)

_L_NEW_TODAY = LaneSpec(
    id="new_today",
    title="New Today",
    description="Roles first observed today.",
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("posted_at", "days_ago"),
    selector=_select_new_today,
)

_L_CLOSING_SOON = LaneSpec(
    id="closing_soon",
    title="Closing Soon",
    description="Roles with a declared close date within seven days.",
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("close_date", "days_until_close"),
    selector=_select_closing_soon,
)

_L_GOVERNMENT = LaneSpec(
    id="government",
    title="Government",
    description="Roles sourced from federal / government portals.",
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("source_ats",),
    selector=_select_government,
)

_L_INTERNSHIPS = LaneSpec(
    id="internships",
    title="Internships",
    description="Roles whose title signals intern or co-op.",
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("title_signal",),
    selector=_select_internships,
)

_L_APPRENTICESHIPS = LaneSpec(
    id="apprenticeships",
    title="Apprenticeships",
    description="Roles whose title signals apprenticeship.",
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("title_signal",),
    selector=_select_apprenticeships,
)

_L_OUTSIDE_USUAL = LaneSpec(
    id="outside_my_usual_path",
    title="Outside My Usual Path",
    description=(
        "Adjacent roles the platform believes you can grow into — "
        "shown transparently, never as a downgrade."
    ),
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("adjacent_reason", "posted_skills_sample"),
    selector=_select_outside_usual_path,
)

_L_ONE_CREDENTIAL_AWAY = LaneSpec(
    id="one_credential_away",
    title="One Credential Away",
    description=(
        "Roles whose sole missing requirement is one certification "
        "not yet in your Passport."
    ),
    min_n_for_public_render=1,
    lawful_source_available=True,
    reason_schema=("missing_credential",),
    selector=_select_one_credential_away,
)


LANE_REGISTRY: Final[tuple[LaneSpec, ...]] = (
    _L_BEST_FIT,
    _L_FASTEST_CREDIBLE,
    _L_LOCAL_NOW,
    _L_REMOTE_WORLDWIDE,
    _L_VISA_FRIENDLY,
    _L_SPONSORSHIP_POSSIBLE,
    _L_NEW_TODAY,
    _L_CLOSING_SOON,
    _L_GOVERNMENT,
    _L_INTERNSHIPS,
    _L_APPRENTICESHIPS,
    _L_OUTSIDE_USUAL,
    _L_ONE_CREDENTIAL_AWAY,
)


def by_id(lane_id: str) -> LaneSpec | None:
    for l in LANE_REGISTRY:
        if l.id == lane_id:
            return l
    return None

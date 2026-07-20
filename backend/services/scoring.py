"""Scoring service — weighted 0-100 with UNKNOWN renormalization.

WEIGHTS_VERSION is versioned so future scoring changes are auditable.
Never uses zip code or age proxies (feature allowlist).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from services import gate_engine

WEIGHTS_VERSION = "v0.1"

# Weight distribution per Phase 3 brief.
WEIGHTS: dict[str, int] = {
    "role_fit": 25,
    "skills_coverage": 20,
    "experience_band_fit": 10,
    "eligibility_margin": 10,
    "location_comp_fit": 10,
    "freshness": 8,
    "competition_estimate": 7,
    "employer_responsiveness_prior": 5,
    "preference_affinity": 5,
}
assert sum(WEIGHTS.values()) == 100


ReasonDirection = Literal["positive", "negative", "unknown"]


@dataclass
class FactorResult:
    factor: str
    value: float | None  # 0..1 or None for UNKNOWN
    direction: ReasonDirection
    weight_applied: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        # weight_ideal = full weight the factor CAN contribute if resolved (before renormalization).
        # weight_applied is the actual weight used in the composite: 0 when the factor is UNKNOWN.
        # UI counterfactual line uses weight_ideal to say "would count for X points".
        return {
            "factor": self.factor,
            "value": self.value,
            "direction": self.direction,
            "weight_applied": self.weight_applied,
            "weight_ideal": WEIGHTS.get(self.factor, 0),
            "detail": self.detail,
        }


def _role_fit(ctx: dict, job: dict) -> FactorResult:
    prefs_families = {str(x).lower() for x in ((ctx.get("preferences") or {}).get("role_families") or [])}
    fam = str(job.get("taxonomy_family") or "").lower()
    if not prefs_families:
        # No preferences → we cannot rate role fit against user intent.
        return FactorResult("role_fit", None, "unknown", 0, "You haven't set preferred role families yet.")
    if fam in prefs_families:
        return FactorResult("role_fit", 1.0, "positive", WEIGHTS["role_fit"], f"Family '{fam}' is in your preferred families.")
    return FactorResult("role_fit", 0.3, "negative", WEIGHTS["role_fit"], f"Family '{fam}' is outside your preferred families.")


def _skills_coverage(ctx: dict, job: dict) -> FactorResult:
    req = ((job.get("requirements") or {}).get("skills_required") or [])
    req_norm = [str(s).lower() for s in req if s]
    if not req_norm:
        # If JD text is present, do a soft substring match against approved skills.
        jd = str(job.get("jd_text") or "").lower()
        approved = ctx.get("approved_skills") or set()
        soft_hits = {s for s in approved if s and s in jd}
        if approved:
            frac = min(1.0, len(soft_hits) / max(3, len(approved)))
            return FactorResult("skills_coverage", frac, "positive" if frac > 0.5 else "negative",
                                WEIGHTS["skills_coverage"], f"{len(soft_hits)} of your approved skills appear in the JD text.")
        return FactorResult("skills_coverage", None, "unknown", 0, "No structured skills on the job and no approved skills on your Passport.")
    approved = ctx.get("approved_skills") or set()
    hits = sum(1 for s in req_norm if s in approved)
    frac = hits / len(req_norm)
    return FactorResult("skills_coverage", frac,
                        "positive" if frac >= 0.5 else "negative",
                        WEIGHTS["skills_coverage"],
                        f"{hits} of {len(req_norm)} required skills present in your approved Passport.")


def _experience_band_fit(ctx: dict, job: dict) -> FactorResult:
    ymin = ((job.get("requirements") or {}).get("years_min"))
    if ymin is None:
        return FactorResult("experience_band_fit", None, "unknown", 0, "Job did not specify years of experience.")
    yrs = gate_engine._years_of_experience(ctx.get("approved_employment") or [])
    if yrs is None:
        return FactorResult("experience_band_fit", None, "unknown", 0, "Approved employment claims are missing start/end dates.")
    if yrs >= ymin:
        # Cap at 1.0 when the candidate has 1x the requirement; degrade if wildly over.
        ratio = min(1.0, yrs / (ymin * 1.5) if ymin else 1.0)
        return FactorResult("experience_band_fit", max(0.6, ratio), "positive", WEIGHTS["experience_band_fit"],
                            f"~{yrs:.1f} yrs vs {ymin}+ required.")
    return FactorResult("experience_band_fit", max(0.0, yrs / ymin), "negative", WEIGHTS["experience_band_fit"],
                        f"~{yrs:.1f} yrs below {ymin}+ required.")


def _eligibility_margin(ctx: dict, job: dict, gate_result: dict) -> FactorResult:
    if gate_result.get("any_fail"):
        return FactorResult("eligibility_margin", 0.0, "negative", WEIGHTS["eligibility_margin"], "One or more gates failed.")
    unknowns = len(gate_result.get("unknown_reasons") or [])
    total = len(gate_result.get("gates") or []) or 1
    margin = max(0.0, 1.0 - (unknowns / total))
    return FactorResult("eligibility_margin", margin,
                        "positive" if margin > 0.6 else "unknown",
                        WEIGHTS["eligibility_margin"],
                        f"{unknowns} of {total} gates are UNKNOWN.")


def _location_comp_fit(ctx: dict, job: dict) -> FactorResult:
    prefs = ctx.get("preferences") or {}
    user_locs = [str(x).lower() for x in (prefs.get("locations") or [])]
    remote_ok = bool(prefs.get("remote_ok"))
    if not user_locs and not remote_ok and not prefs.get("salary_floor_usd"):
        return FactorResult("location_comp_fit", None, "unknown", 0, "No location or comp preferences set.")
    geo = str(job.get("geo") or "").lower()
    loc_ok = (remote_ok and "remote" in geo) or any(l and (l in geo or geo in l) for l in user_locs)
    floor = prefs.get("salary_floor_usd")
    posted_low = gate_engine._parse_comp_low(job.get("comp"))
    comp_ok = None if floor is None else (posted_low is not None and posted_low >= floor)
    # Compose
    pieces = []
    if loc_ok is True: pieces.append(1.0)
    if loc_ok is False: pieces.append(0.2)
    if comp_ok is True: pieces.append(1.0)
    if comp_ok is False: pieces.append(0.3)
    if not pieces:
        return FactorResult("location_comp_fit", None, "unknown", 0, "Neither location nor comp comparable.")
    val = sum(pieces) / len(pieces)
    return FactorResult("location_comp_fit", val,
                        "positive" if val >= 0.6 else "negative",
                        WEIGHTS["location_comp_fit"],
                        f"Location match={loc_ok if loc_ok is not None else 'n/a'}, comp match={comp_ok if comp_ok is not None else 'n/a'}.")


def _freshness(ctx: dict, job: dict) -> FactorResult:
    lv = job.get("last_verified")
    if not isinstance(lv, datetime):
        return FactorResult("freshness", None, "unknown", 0, "No verification timestamp on the job.")
    if lv.tzinfo is None:
        lv = lv.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - lv).days
    val = max(0.0, 1.0 - (days / 14.0))
    return FactorResult("freshness", val,
                        "positive" if days <= 3 else ("negative" if days > 10 else "unknown"),
                        WEIGHTS["freshness"],
                        f"Verified {days} day(s) ago.")


def _competition_estimate(ctx: dict, job: dict) -> FactorResult:
    # Honest v0.1: no signal → UNKNOWN and renormalize.
    return FactorResult("competition_estimate", None, "unknown", 0, "No competition signal yet.")


def _employer_responsiveness(ctx: dict, job: dict) -> FactorResult:
    return FactorResult("employer_responsiveness_prior", None, "unknown", 0, "No employer response data yet.")


def _preference_affinity(ctx: dict, job: dict) -> FactorResult:
    prefs = ctx.get("preferences") or {}
    inc = {str(x).lower() for x in (prefs.get("employer_include") or [])}
    exc = {str(x).lower() for x in (prefs.get("employer_exclude") or [])}
    domain = str(job.get("company_domain") or "").lower()
    name = str(job.get("company_name") or "").lower()
    if any(x and (x in domain or x in name) for x in exc):
        return FactorResult("preference_affinity", 0.0, "negative", WEIGHTS["preference_affinity"], "Employer is on your exclude list.")
    if any(x and (x in domain or x in name) for x in inc):
        return FactorResult("preference_affinity", 1.0, "positive", WEIGHTS["preference_affinity"], "Employer is on your include list.")
    if not inc and not exc:
        return FactorResult("preference_affinity", None, "unknown", 0, "No employer include/exclude lists.")
    return FactorResult("preference_affinity", 0.5, "unknown", WEIGHTS["preference_affinity"], "Employer not on either list.")


def score(context: dict, job: dict, gate_result: dict) -> dict[str, Any]:
    """Return {score, confidence, factors, reason_codes, weights_version}. Renormalizes UNKNOWNs.

    If any gate FAILED, we still emit a score but flag reason_codes strongly negatively so the UI is
    honest. The feed only shows gate-passing jobs anyway, but S9 needs the analytics to be complete.
    """
    factors: list[FactorResult] = [
        _role_fit(context, job),
        _skills_coverage(context, job),
        _experience_band_fit(context, job),
        _eligibility_margin(context, job, gate_result),
        _location_comp_fit(context, job),
        _freshness(context, job),
        _competition_estimate(context, job),
        _employer_responsiveness(context, job),
        _preference_affinity(context, job),
    ]

    used_weight = sum(f.weight_applied for f in factors)
    unused_weight = 100 - used_weight
    if used_weight == 0:
        raw = 0.0
    else:
        raw = sum((f.value or 0.0) * f.weight_applied for f in factors) / used_weight * 100
    # If a gate has failed, cap the score aggressively.
    if gate_result.get("any_fail"):
        raw = min(raw, 25.0)
    confidence = round(used_weight / 100.0, 3)
    reason_codes = [f.to_dict() for f in factors if f.weight_applied > 0]
    # Also record UNKNOWN factors as informational (weight 0) so S9 shows them as gray bars.
    reason_codes += [f.to_dict() for f in factors if f.weight_applied == 0]
    return {
        "score": round(raw, 2),
        "confidence": confidence,
        "reason_codes": reason_codes,
        "unused_weight": unused_weight,
        "weights_version": WEIGHTS_VERSION,
    }

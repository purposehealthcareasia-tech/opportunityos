"""Gate engine — full ordered sequence for Phase 3.

One engine, two consumers: the coverage preview (S6) and the feed (S7) MUST produce
identical gate results for the same (user, job) pair. Do not fork this file.

FEATURE ALLOWLIST: gates and scoring must not use zip code or age proxies. Ever.

14-gate contract (Founder Directive #3):

  1. vacancy_open           — job.status == 'live' and not stale
  2. authorization_scope    — per-application submit authorization (INTERFACE ONLY in Phase 3; enforced at submit-time in Phase 5)
  3. duplicate_check        — no non-closed application for (user, job)
  4. work_auth              — job.eligibility_requirements.accepted_statuses vs candidate status
  5. sponsorship            — sponsor-needed candidate vs employer offers_sponsorship
  6. stem_opt_viability     — E-Verify/STEM-OPT window vs plausible start
  7. itar                   — requires_us_person vs candidate status
  8. security_clearance     — job requires clearance vs candidate holds clearance
  9. licensure              — job requires listed license vs candidate holds it
 10. location_onsite        — job geo vs preferences (locations / remote_ok)
 11. experience_band        — years_min vs candidate approved employment years
 12. education_requirement  — degree_level vs candidate approved education level
 13. salary_floor           — user prefs floor vs posted comp range
 14. employer_exclusions    — company domain in user's exclude list

Duplicate + authorization_scope are the two "submit-time" gates; duplicate is fully
enforced today because we have an applications collection. authorization_scope is
enumerated today but always "pass" — Phase 5 activates it.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal
import re
from core.db import get_db
from core.config import settings

GateStatus = Literal["pass", "fail", "unknown"]

US_PERSON_STATUSES = {"citizen", "permanent_resident"}
NEEDS_SPONSORSHIP_STATUSES = {"ead_opt", "stem_opt", "h1b", "tn", "other"}

DEGREE_ORDER = {"HS": 0, "AS": 1, "BS": 2, "MS": 3, "PhD": 4}


@dataclass
class GateResult:
    name: str
    status: GateStatus
    reason: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "reason": self.reason, "detail": self.detail}


# ---------- Context builder ----------
async def build_context(user_id: str) -> dict:
    db = get_db()
    prefs_row = await db.preferences.find_one({"user_id": user_id}, sort=[("version", -1)])
    elig_row = await db.eligibility_profiles.find_one({"user_id": user_id}, sort=[("version", -1)])
    claims_cur = db.claims.find({"user_id": user_id, "status": "approved", "superseded_by": None})
    approved_skills: set[str] = set()
    approved_education: list[dict] = []
    approved_employment: list[dict] = []
    approved_certifications: list[dict] = []
    async for c in claims_cur:
        t = c.get("type"); v = c.get("value") or {}
        if t == "skill" and v.get("name"):
            approved_skills.add(str(v["name"]).strip().lower())
        elif t == "education":
            approved_education.append(v)
        elif t == "employment":
            approved_employment.append(v)
        elif t == "certification":
            approved_certifications.append(v)
    apps_cur = db.applications.find({"user_id": user_id, "state": {"$ne": "closed"}}, {"job_id": 1, "_id": 0})
    existing_apps = {a["job_id"] async for a in apps_cur}
    hidden_cur = db.hidden_jobs.find({"user_id": user_id}, {"job_id": 1, "_id": 0})
    hidden_ids = {h["job_id"] async for h in hidden_cur}
    return {
        "user_id": user_id,
        "eligibility": elig_row or {},
        "preferences": (prefs_row or {}).get("payload") or {},
        "approved_skills": approved_skills,
        "approved_education": approved_education,
        "approved_employment": approved_employment,
        "approved_certifications": approved_certifications,
        "existing_applications": existing_apps,
        "hidden_job_ids": hidden_ids,
    }


# ---------- Helpers ----------
def _is_stale(job: dict) -> bool:
    ts = job.get("last_verified")
    if not isinstance(ts, datetime):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts) > timedelta(days=settings.JOB_STALENESS_DAYS)


def _highest_degree(edu_list: Iterable[dict]) -> str | None:
    best = None
    for e in edu_list:
        d = str(e.get("degree") or "").upper().strip()
        if d in DEGREE_ORDER:
            if best is None or DEGREE_ORDER[d] > DEGREE_ORDER[best]:
                best = d
    return best


def _years_of_experience(emp_list: Iterable[dict]) -> float | None:
    total = 0.0
    counted = False
    for emp in emp_list:
        # We only credit "years" if explicit start/end YYYY-MM(-DD) style. Otherwise UNKNOWN.
        s = str(emp.get("start") or "")
        e = str(emp.get("end") or "")
        try:
            sd = datetime.strptime(s[:7], "%Y-%m") if s else None
            ed = datetime.strptime(e[:7], "%Y-%m") if e else datetime.now(timezone.utc).replace(tzinfo=None)
            if sd:
                delta = (ed - sd).days / 365.25
                if delta > 0:
                    total += delta
                    counted = True
        except ValueError:
            continue
    return total if counted else None


def _parse_comp_low(comp: str | None) -> int | None:
    if not comp:
        return None
    m = re.search(r"\$?\s*(\d{2,3})[,]?(\d{3})?\s*[kK]?", comp)
    if not m:
        return None
    a = m.group(1); b = m.group(2)
    if b:
        val = int(a) * 1000 + int(b)
    else:
        # if 2-3 digit followed by k, treat as thousands. Otherwise just the number.
        val = int(a) * 1000 if "k" in comp.lower() else int(a)
    return val


def _extract_jd_skill_hits(jd_text: str, approved: set[str]) -> tuple[set[str], set[str]]:
    """Return (matched_skills, jd_referenced_skills). Case-insensitive substring hits."""
    hay = (jd_text or "").lower()
    matched = {s for s in approved if s and s in hay}
    return matched, matched  # for v0.1 keep them the same set


# ---------- Individual gates ----------
def _gate_vacancy_open(ctx: dict, job: dict) -> GateResult:
    st = job.get("status")
    if st != "live":
        return GateResult("vacancy_open", "fail", reason="job_not_live", detail=f"Job status is {st}.")
    if _is_stale(job):
        return GateResult("vacancy_open", "fail", reason="job_stale", detail="Not verified in the last 14 days.")
    return GateResult("vacancy_open", "pass")


def _gate_duplicate(ctx: dict, job: dict) -> GateResult:
    if job.get("id") in (ctx.get("existing_applications") or set()):
        return GateResult("duplicate_check", "fail", reason="duplicate_application", detail="You already have an open application for this job.")
    return GateResult("duplicate_check", "pass")


def _gate_work_auth(ctx: dict, job: dict) -> GateResult:
    accepted = (job.get("eligibility_requirements") or {}).get("accepted_statuses")
    status = (ctx.get("eligibility") or {}).get("status") or "unspecified"
    if not accepted:
        return GateResult("work_auth", "pass")
    if status == "unspecified":
        return GateResult("work_auth", "unknown", reason="work_auth_unspecified")
    if status in accepted:
        return GateResult("work_auth", "pass")
    return GateResult("work_auth", "fail", reason="work_auth_mismatch", detail=f"Job accepts {sorted(accepted)}; you are {status}.")


def _gate_sponsorship(ctx: dict, job: dict) -> GateResult:
    status = (ctx.get("eligibility") or {}).get("status") or "unspecified"
    if status not in NEEDS_SPONSORSHIP_STATUSES:
        return GateResult("sponsorship", "pass")
    offers = (job.get("eligibility_requirements") or {}).get("offers_sponsorship")
    if offers is False:
        return GateResult("sponsorship", "fail", reason="no_sponsorship_offered", detail="Employer does not offer sponsorship for this role.")
    if offers is True:
        return GateResult("sponsorship", "pass")
    return GateResult("sponsorship", "unknown", reason="sponsorship_unknown", detail="Employer sponsorship policy not stated.")


def _gate_stem_opt_viability(ctx: dict, job: dict) -> GateResult:
    elig = ctx.get("eligibility") or {}
    if elig.get("status") != "stem_opt":
        return GateResult("stem_opt_viability", "pass")
    dates = elig.get("dates") or {}
    opt_end = dates.get("opt_end")
    if not opt_end:
        return GateResult("stem_opt_viability", "unknown", reason="stem_opt_end_missing")
    try:
        end = datetime.strptime(opt_end[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return GateResult("stem_opt_viability", "unknown", reason="stem_opt_end_unparseable")
    # Basic viability: OPT must extend past a plausible earliest start (~30 days out) with 90+ days runway.
    plausible_start = datetime.now(timezone.utc) + timedelta(days=30)
    if end < plausible_start + timedelta(days=90):
        return GateResult("stem_opt_viability", "fail", reason="stem_opt_expires_soon", detail=f"STEM OPT ends {opt_end}; too little runway to reasonably start.")
    return GateResult("stem_opt_viability", "pass")


def _gate_itar(ctx: dict, job: dict) -> GateResult:
    req = (job.get("eligibility_requirements") or {})
    if not req.get("requires_us_person"):
        return GateResult("itar", "pass")
    status = (ctx.get("eligibility") or {}).get("status") or "unspecified"
    if status == "unspecified":
        return GateResult("itar", "unknown", reason="work_auth_unspecified", detail="US-person requirement present; you have not declared status.")
    if status in US_PERSON_STATUSES:
        return GateResult("itar", "pass")
    return GateResult("itar", "fail", reason="requires_us_person", detail="Job requires US-person status (ITAR / export-controlled).")


def _gate_security_clearance(ctx: dict, job: dict) -> GateResult:
    req = (job.get("eligibility_requirements") or {})
    needed = req.get("requires_security_clearance")
    if not needed:
        return GateResult("security_clearance", "pass")
    # We do not track clearance claims in Phase 3; UNKNOWN if a job needs one.
    return GateResult("security_clearance", "unknown", reason="clearance_unknown", detail="Job requires a clearance; your Passport doesn't declare one.")


def _gate_licensure(ctx: dict, job: dict) -> GateResult:
    reqs = ((job.get("requirements") or {}).get("licenses") or [])
    if not reqs:
        return GateResult("licensure", "pass")
    held = {str(c.get("name") or "").lower() for c in ctx.get("approved_certifications") or []}
    missing = [r for r in reqs if r.lower() not in held]
    if not missing:
        return GateResult("licensure", "pass")
    return GateResult("licensure", "unknown", reason="licensure_gap", detail=f"Job asks for {reqs}; you haven't approved a matching credential.")


def _gate_location(ctx: dict, job: dict) -> GateResult:
    prefs = ctx.get("preferences") or {}
    remote_ok = bool(prefs.get("remote_ok"))
    user_locs = [str(x).lower() for x in (prefs.get("locations") or [])]
    if not user_locs and not remote_ok:
        # No preferences → treat as any-location OK
        return GateResult("location_onsite", "pass")
    geo = str(job.get("geo") or "").lower()
    if remote_ok and "remote" in geo:
        return GateResult("location_onsite", "pass")
    for loc in user_locs:
        if loc and (loc in geo or geo in loc):
            return GateResult("location_onsite", "pass")
    if geo:
        return GateResult("location_onsite", "fail", reason="location_mismatch", detail=f"Job is in {job.get('geo')}; not in your locations {prefs.get('locations')}.")
    return GateResult("location_onsite", "unknown", reason="location_unknown")


def _gate_experience_band(ctx: dict, job: dict) -> GateResult:
    ymin = ((job.get("requirements") or {}).get("years_min"))
    if ymin is None:
        return GateResult("experience_band", "pass")
    yrs = _years_of_experience(ctx.get("approved_employment") or [])
    if yrs is None:
        return GateResult("experience_band", "unknown", reason="experience_missing", detail="No explicit start/end dates in your approved employment claims.")
    if yrs + 0.25 < ymin:
        return GateResult("experience_band", "fail", reason="experience_below_band", detail=f"Job asks for {ymin}+ years; ~{yrs:.1f} inferred from your approved employment.")
    return GateResult("experience_band", "pass")


def _gate_education(ctx: dict, job: dict) -> GateResult:
    req = ((job.get("requirements") or {}).get("degree_level"))
    if not req:
        return GateResult("education_requirement", "pass")
    have = _highest_degree(ctx.get("approved_education") or [])
    if not have:
        return GateResult("education_requirement", "unknown", reason="education_unknown", detail=f"Job asks for {req}; no approved education claim yet.")
    if DEGREE_ORDER.get(have, -1) >= DEGREE_ORDER.get(req.upper(), 0):
        return GateResult("education_requirement", "pass")
    return GateResult("education_requirement", "fail", reason="education_below_requirement", detail=f"Job asks for {req}; your highest approved degree is {have}.")


def _gate_salary(ctx: dict, job: dict) -> GateResult:
    floor = (ctx.get("preferences") or {}).get("salary_floor_usd")
    if not floor:
        return GateResult("salary_floor", "pass")
    posted = _parse_comp_low(job.get("comp"))
    if posted is None:
        return GateResult("salary_floor", "unknown", reason="no_comp_posted", detail="Employer did not post compensation.")
    if posted >= floor:
        return GateResult("salary_floor", "pass")
    return GateResult("salary_floor", "fail", reason="below_salary_floor", detail=f"Posted low end ${posted:,} < your floor ${int(floor):,}.")


def _gate_employer_exclusions(ctx: dict, job: dict) -> GateResult:
    excludes = {str(x).lower() for x in ((ctx.get("preferences") or {}).get("employer_exclude") or [])}
    if not excludes:
        return GateResult("employer_exclusions", "pass")
    # Company domain: we store company_id; look up company doc? Use job.company_name lowercased.
    name = str(job.get("company_name") or "").lower()
    if any(x in name for x in excludes):
        return GateResult("employer_exclusions", "fail", reason="employer_excluded", detail=f"'{job.get('company_name')}' is on your exclude list.")
    return GateResult("employer_exclusions", "pass")


def _gate_authorization_scope(ctx: dict, job: dict) -> GateResult:
    """Gate #14 — INTERFACE ONLY in Phase 3.

    Per Founder Directive #3: authorization-scope enforcement runs at approval/submit time
    (lands with Phase 5 submit path). Feed/coverage-preview always report "pass" here so the
    gate slot is enumerated in the response and downstream code paths can rely on 14 gates,
    but no user is blocked from browsing on authorization-scope grounds today.

    When Phase 5 wires submit, this gate will read `authorization_scopes` and confirm the user
    has granted a per-application submit authorization matching (job_id, materials manifest hash).
    """
    return GateResult(
        "authorization_scope",
        "pass",
        detail="Interface only in Phase 3. Enforced at submit-time (lands with Phase 5).",
    )


GATES = [
    _gate_vacancy_open,
    _gate_authorization_scope,   # #14 — interface only; enforced at submit-time
    _gate_duplicate,
    _gate_work_auth,
    _gate_sponsorship,
    _gate_stem_opt_viability,
    _gate_itar,
    _gate_security_clearance,
    _gate_licensure,
    _gate_location,
    _gate_experience_band,
    _gate_education,
    _gate_salary,
    _gate_employer_exclusions,
]


def evaluate(context: dict, job: dict) -> dict[str, Any]:
    results = [g(context, job) for g in GATES]
    pass_all = all(r.status == "pass" for r in results)
    any_fail = any(r.status == "fail" for r in results)
    any_unknown = any(r.status == "unknown" for r in results)
    fail_reasons = [r.reason for r in results if r.status == "fail" and r.reason]
    unknown_reasons = [r.reason for r in results if r.status == "unknown" and r.reason]
    return {
        "gates": [r.to_dict() for r in results],
        "pass_all": pass_all,
        "any_fail": any_fail,
        "any_unknown": any_unknown,
        "fail_reasons": fail_reasons,
        "unknown_reasons": unknown_reasons,
    }


def derive_flags(status: str | None) -> dict[str, bool]:
    s = (status or "unspecified").lower()
    return {
        "itar_excluded": s not in US_PERSON_STATUSES and s != "unspecified",
        "e_verify_need": s in {"stem_opt", "ead_opt", "h1b", "tn"},
        "sponsorship_need": s in NEEDS_SPONSORSHIP_STATUSES,
    }

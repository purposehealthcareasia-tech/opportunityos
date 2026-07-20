"""Gate engine v0 — evaluate a candidate's eligibility profile against a single job's requirements.

Designed to be extended in Phase 3 with employer green-lane rules, seniority filters, etc.
"""
from dataclasses import dataclass
from typing import Any, Literal

GateStatus = Literal["pass", "fail", "unknown"]


@dataclass
class GateResult:
    name: str
    status: GateStatus
    reason: str | None = None  # short reason_code
    detail: str | None = None  # human-readable

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "reason": self.reason, "detail": self.detail}


US_PERSON_STATUSES = {"citizen", "permanent_resident"}
NEEDS_SPONSORSHIP_STATUSES = {"ead_opt", "stem_opt", "h1b", "tn", "other"}


def _work_auth_gate(profile: dict, job: dict) -> GateResult:
    status = (profile or {}).get("status") or "unspecified"
    accepted = (job or {}).get("eligibility_requirements", {}).get("accepted_statuses")
    if not accepted:
        return GateResult("work_auth", "pass", detail="No explicit work-auth allow-list on this job.")
    if status == "unspecified":
        return GateResult("work_auth", "unknown", reason="work_auth_unspecified", detail="Candidate has not declared work authorization.")
    if status in accepted:
        return GateResult("work_auth", "pass")
    return GateResult("work_auth", "fail", reason="work_auth_mismatch", detail=f"Job accepts {sorted(accepted)}; candidate is {status}.")


def _itar_gate(profile: dict, job: dict) -> GateResult:
    req = (job or {}).get("eligibility_requirements", {})
    if not req.get("requires_us_person"):
        return GateResult("itar", "pass")
    status = (profile or {}).get("status") or "unspecified"
    if status == "unspecified":
        return GateResult("itar", "unknown", reason="work_auth_unspecified", detail="US-person requirement present, candidate has not declared status.")
    if status in US_PERSON_STATUSES:
        return GateResult("itar", "pass")
    return GateResult("itar", "fail", reason="requires_us_person", detail="Job requires US-person status (ITAR / export-controlled).")


def _sponsorship_gate(profile: dict, job: dict) -> GateResult:
    status = (profile or {}).get("status") or "unspecified"
    if status not in NEEDS_SPONSORSHIP_STATUSES:
        # Candidate does not need sponsorship (citizen / PR / unspecified). Gate is a pass regardless.
        return GateResult("sponsorship", "pass")
    offers = (job or {}).get("eligibility_requirements", {}).get("offers_sponsorship")
    if offers is False:
        return GateResult("sponsorship", "fail", reason="no_sponsorship_offered", detail="Employer does not offer sponsorship for this role.")
    if offers is True:
        return GateResult("sponsorship", "pass")
    return GateResult("sponsorship", "unknown", reason="sponsorship_unknown", detail="Employer sponsorship policy not stated on the listing.")


GATES = [_work_auth_gate, _itar_gate, _sponsorship_gate]


def evaluate(profile: dict, job: dict) -> dict[str, Any]:
    results = [g(profile, job) for g in GATES]
    fail_reasons = [r.reason for r in results if r.status == "fail" and r.reason]
    unknown_reasons = [r.reason for r in results if r.status == "unknown" and r.reason]
    pass_all = all(r.status == "pass" for r in results)
    return {
        "gates": [r.to_dict() for r in results],
        "pass_all": pass_all,
        "any_fail": any(r.status == "fail" for r in results),
        "any_unknown": any(r.status == "unknown" for r in results),
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

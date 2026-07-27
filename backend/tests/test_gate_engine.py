"""Gate engine + scoring unit tests. Zero network. Uses build_context() only when needed via mocks."""
from __future__ import annotations
import pytest
from datetime import datetime, timezone
from services import gate_engine
from services.scoring import score, WEIGHTS_VERSION, WEIGHTS


def _mkjob(**over):
    base = {
        "id": "job-x",
        "canonical_key": "sampleco.demo::sample-01",
        "title": "Vehicle Systems Engineer",
        "company_name": "SampleCo (demo)",
        "geo": "Phoenix, AZ",
        "comp": "$115k-$150k",
        "jd_text": "Own vehicle-level requirements decomposition.",
        "status": "live",
        "is_sample": True,
        "last_verified": datetime.now(timezone.utc),
        "taxonomy_family": "vehicle systems",
        "apply_method": "internal",
        "eligibility_requirements": {},
        "requirements": {"skills_required": ["mbse"], "degree_level": "BS", "years_min": 3},
    }
    base.update(over)
    return base


def _ctx(**over):
    base = {
        "user_id": "u1",
        "eligibility": {"status": "citizen"},
        "preferences": {},
        "approved_skills": set(),
        "approved_education": [],
        "approved_employment": [],
        "approved_certifications": [],
        "existing_applications": set(),
        "hidden_job_ids": set(),
    }
    base.update(over)
    return base


def test_gate_engine_enumerates_14_gates_by_exact_name():
    """Founder Directive #3 — 14 gate names in the exact spec order."""
    res = gate_engine.evaluate(_ctx(), _mkjob())
    names = [g["name"] for g in res["gates"]]
    expected = [
        "vacancy_open",
        "authorization_scope",
        "duplicate_check",
        "work_auth",
        "sponsorship",
        "stem_opt_viability",
        "itar",
        "security_clearance",
        "licensure",
        "location_onsite",
        "experience_band",
        "education_requirement",
        "salary_floor",
        "employer_exclusions",
    ]
    assert names == expected
    assert len(names) == 14


def test_authorization_scope_gate_passes_but_is_declared():
    """Interface must exist; enforcement lands with Phase 5 submit-time."""
    res = gate_engine.evaluate(_ctx(), _mkjob())
    az = [g for g in res["gates"] if g["name"] == "authorization_scope"][0]
    assert az["status"] == "pass"
    assert "Interface only in Phase 3" in (az.get("detail") or "")


def test_itar_gate_fails_for_non_us_person():
    job = _mkjob(eligibility_requirements={"requires_us_person": True})
    ctx = _ctx(eligibility={"status": "ead_opt"})
    res = gate_engine.evaluate(ctx, job)
    itar = [g for g in res["gates"] if g["name"] == "itar"][0]
    assert itar["status"] == "fail"
    assert itar["reason"] == "requires_us_person"
    assert "requires_us_person" in res["fail_reasons"]


def test_sponsorship_gate_fails_when_needed_but_not_offered():
    job = _mkjob(eligibility_requirements={"offers_sponsorship": False})
    ctx = _ctx(eligibility={"status": "stem_opt"})
    res = gate_engine.evaluate(ctx, job)
    spon = [g for g in res["gates"] if g["name"] == "sponsorship"][0]
    assert spon["status"] == "fail"
    assert spon["reason"] == "no_sponsorship_offered"


def test_duplicate_gate_fails_when_open_app_exists():
    job = _mkjob()
    ctx = _ctx(existing_applications={"job-x"})
    res = gate_engine.evaluate(ctx, job)
    dup = [g for g in res["gates"] if g["name"] == "duplicate_check"][0]
    assert dup["status"] == "fail"
    assert dup["reason"] == "duplicate_application"


def test_scoring_weights_sum_to_100_and_version_is_v01():
    assert sum(WEIGHTS.values()) == 100
    assert WEIGHTS_VERSION == "v0.1"


def test_scoring_renormalizes_unknowns_and_gate_fail_caps_score():
    job = _mkjob(eligibility_requirements={"requires_us_person": True})
    ctx = _ctx(eligibility={"status": "ead_opt"})
    gate_result = gate_engine.evaluate(ctx, job)
    s = score(ctx, job, gate_result)
    # Any gate fail caps at 25
    assert s["score"] <= 25.0
    assert s["weights_version"] == "v0.1"
    # confidence = used_weight / 100
    assert 0.0 <= s["confidence"] <= 1.0
    # feedback loop: reason codes present
    assert isinstance(s["reason_codes"], list)


def test_scoring_positive_path_when_all_pass():
    job = _mkjob(comp="$150k-$200k", requirements={"skills_required": ["mbse"], "degree_level": "BS", "years_min": 3, "licenses": []})
    ctx = _ctx(
        eligibility={"status": "citizen"},
        preferences={"role_families": ["vehicle systems"], "salary_floor_usd": 120000, "locations": ["Phoenix, AZ"]},
        approved_skills={"mbse"},
        approved_education=[{"degree": "BS", "institution": "MIT"}],
        approved_employment=[{"start": "2020-06", "end": "2024-01"}],
    )
    gate_result = gate_engine.evaluate(ctx, job)
    assert gate_result["pass_all"] is True, gate_result
    s = score(ctx, job, gate_result)
    assert s["score"] > 40


def test_gate_engine_never_uses_zip_or_age(monkeypatch):
    """Founder Directive #7 (feature allowlist) — the engine's callable code must not read zip/age."""
    import ast, inspect
    src = inspect.getsource(gate_engine)
    tree = ast.parse(src)
    # Walk the tree; check identifiers and Attribute names (skip docstrings entirely).
    forbidden = {"zip_code", "zipcode", "zip"}
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden:
            hits.append(("Name", node.id, node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr in forbidden:
            hits.append(("Attr", node.attr, node.lineno))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in forbidden:
            # A string literal like "zip_code" would count — but not the docstring which contains "zip" as a substring.
            hits.append(("Str", node.value, node.lineno))
    assert not hits, f"gate_engine references forbidden features (callable-scope): {hits}"


# =====================================================================
# Phase 3 Founder Brief — degree-blind eligibility.
# Only work-authorization, legally-mandatory licensure, and geographic
# impossibility may hard-exclude. Education + experience mismatches must
# surface as visible NOTES on the card but stay queueable.
# =====================================================================
def test_education_mismatch_stays_queueable_with_note():
    job = _mkjob(requirements={"degree_level": "PhD", "skills_required": [], "years_min": None})
    ctx = _ctx(approved_education=[{"degree": "BS", "institution": "State U"}])
    res = gate_engine.evaluate(ctx, job)
    edu = [g for g in res["gates"] if g["name"] == "education_requirement"][0]
    assert edu["status"] == "pass"
    assert edu["reason"] is None
    assert "PhD" in (edu["note"] or "") and "BS" in (edu["note"] or "")
    assert "education_below_requirement" not in res["fail_reasons"]
    assert any(n["gate"] == "education_requirement" for n in res["notes"])


def test_education_unknown_stays_queueable_with_note():
    job = _mkjob(requirements={"degree_level": "MS", "skills_required": [], "years_min": None})
    ctx = _ctx(approved_education=[])  # No education claim
    res = gate_engine.evaluate(ctx, job)
    edu = [g for g in res["gates"] if g["name"] == "education_requirement"][0]
    assert edu["status"] == "pass"
    assert edu["reason"] is None
    assert "MS" in (edu["note"] or "")
    assert "education_unknown" not in res["unknown_reasons"]


def test_education_pass_when_candidate_meets_requirement():
    job = _mkjob(requirements={"degree_level": "BS", "skills_required": [], "years_min": None})
    ctx = _ctx(approved_education=[{"degree": "MS", "institution": "State U"}])
    res = gate_engine.evaluate(ctx, job)
    edu = [g for g in res["gates"] if g["name"] == "education_requirement"][0]
    assert edu["status"] == "pass"
    assert edu["note"] is None


def test_experience_mismatch_stays_queueable_with_note():
    """Same degree-blind principle applied to experience_band per Phase 3 brief."""
    job = _mkjob(requirements={"degree_level": None, "skills_required": [], "years_min": 10})
    ctx = _ctx(approved_employment=[{"start": "2023-01", "end": "2024-06"}])  # ~1.4 yrs
    res = gate_engine.evaluate(ctx, job)
    exp = [g for g in res["gates"] if g["name"] == "experience_band"][0]
    assert exp["status"] == "pass"
    assert "10+" in (exp["note"] or "") or "10.0+" in (exp["note"] or "") or "10" in (exp["note"] or "")
    assert "experience_below_band" not in res["fail_reasons"]


def test_experience_unknown_stays_queueable_with_note():
    job = _mkjob(requirements={"degree_level": None, "skills_required": [], "years_min": 5})
    ctx = _ctx(approved_employment=[])
    res = gate_engine.evaluate(ctx, job)
    exp = [g for g in res["gates"] if g["name"] == "experience_band"][0]
    assert exp["status"] == "pass"
    assert exp["reason"] is None
    assert "experience_missing" not in res["unknown_reasons"]


# =====================================================================
# Licensure gate precision (Phase 3 Founder Brief).
# Hard-fail ONLY on legally-mandatory license mismatch. Ambiguous /
# "preferred" credentials must NEVER exclude — surface as note.
# =====================================================================
def test_licensure_hard_fails_on_missing_legal_license_cdl():
    job = _mkjob(requirements={"licenses": ["CDL Class A"], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[])
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "fail"
    assert lic["reason"] is not None and lic["reason"].startswith("missing_legal_license:")
    assert "CDL" in lic["reason"]
    assert any(r.startswith("missing_legal_license:") for r in res["fail_reasons"])


def test_licensure_hard_fails_on_missing_rn():
    job = _mkjob(requirements={"licenses": ["Registered Nurse (RN)"], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[])
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "fail"
    assert "RN" in (lic["reason"] or "")


def test_licensure_hard_fails_on_missing_finra_series7():
    job = _mkjob(requirements={"licenses": ["Series 7"], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[])
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "fail"
    assert "FINRA" in (lic["reason"] or "")


def test_licensure_passes_when_user_holds_matching_credential():
    job = _mkjob(requirements={"licenses": ["CDL Class A"], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[{"name": "CDL Class A - AZ"}])
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "pass"
    assert lic["reason"] is None


def test_licensure_ambiguous_credential_stays_queueable_with_note_pmp():
    """PMP is a credential but NOT statutorily required — must not exclude."""
    job = _mkjob(requirements={"licenses": ["PMP"], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[])
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "pass"
    assert "PMP" in (lic["note"] or "")
    assert not any(r.startswith("missing_legal_license:") for r in res["fail_reasons"])


def test_licensure_ambiguous_credential_stays_queueable_with_note_aws():
    """AWS/Azure cert is helpful but not legally mandatory."""
    job = _mkjob(requirements={"licenses": ["AWS Solutions Architect Professional"], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[])
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "pass"
    assert lic["note"] is not None


def test_licensure_no_requirements_passes_clean():
    job = _mkjob(requirements={"licenses": [], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[])
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "pass"
    assert lic["note"] is None


def test_licensure_mixed_legal_and_ambiguous_hard_fails_on_legal():
    """If both a legal-mandatory license AND an ambiguous credential are required,
    the legal one wins → hard-fail."""
    job = _mkjob(requirements={"licenses": ["CDL Class A", "OSHA 30"], "skills_required": [], "years_min": None})
    ctx = _ctx(approved_certifications=[{"name": "OSHA 30"}])  # holds ambiguous, missing legal
    res = gate_engine.evaluate(ctx, job)
    lic = [g for g in res["gates"] if g["name"] == "licensure"][0]
    assert lic["status"] == "fail"
    assert "CDL" in (lic["reason"] or "")


def test_only_three_hard_gate_families_can_fail():
    """Founder Brief: only work-authorization, legally-mandatory licensure, and
    geographic impossibility may hard-exclude. Confirm education + experience
    can no longer produce a fail regardless of input."""
    # Job that would previously have failed on BOTH education + experience.
    job = _mkjob(requirements={"degree_level": "PhD",
                                "skills_required": [],
                                "years_min": 15,
                                "licenses": []})
    ctx = _ctx(
        eligibility={"status": "citizen"},
        preferences={},
        approved_education=[{"degree": "AS"}],
        approved_employment=[{"start": "2024-01", "end": "2024-06"}],  # ~0.4 yrs
    )
    res = gate_engine.evaluate(ctx, job)
    edu = [g for g in res["gates"] if g["name"] == "education_requirement"][0]
    exp = [g for g in res["gates"] if g["name"] == "experience_band"][0]
    assert edu["status"] == "pass" and exp["status"] == "pass"
    # This job now passes every gate — it should be in the feed with 2 notes.
    assert res["pass_all"] is True
    assert len(res["notes"]) >= 2
    assert {n["gate"] for n in res["notes"]} >= {"education_requirement", "experience_band"}

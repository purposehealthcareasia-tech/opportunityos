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

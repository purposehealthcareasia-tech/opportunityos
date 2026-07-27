"""Phase 3 Founder Brief safeguards — unit tests.

Covers:
  * velocity estimator (income-velocity for Lane B "soonest money" sort)
  * employer_cap (rolling 30-day per-employer cap)
  * credentials catalog integrity
  * gate_engine notes propagation
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import velocity as vel
from services import employer_cap as cap
from services import gate_engine
from domains.credentials import get_catalog, by_id


# =====================================================================
# Velocity estimator — deterministic, no network.
# =====================================================================
def test_velocity_parses_hourly_rate_range_from_jd():
    job = {"jd_text": "Compensation: $18.50 - $22.00 per hour based on experience.",
           "comp": ""}
    est = vel.estimate(job)
    assert est["hourly_rate_usd"] is not None
    assert 18.4 <= est["hourly_rate_usd"] <= 22.1
    assert est["hours_per_week"] == 40
    assert est["weekly_est_usd"] is not None
    assert est["velocity_score"] is not None


def test_velocity_parses_single_hourly_rate():
    job = {"jd_text": "Starting at $19/hour", "comp": ""}
    est = vel.estimate(job)
    assert est["hourly_rate_usd"] == 19.0
    assert est["hours_per_week"] == 40
    assert est["weekly_est_usd"] == 760.0


def test_velocity_falls_back_to_salary_range():
    job = {"jd_text": "$80,000 - $120,000 per year",
           "comp": "$80k-$120k", "discovery": {}}
    est = vel.estimate(job)
    assert est["hourly_rate_usd"] is not None
    # (80000 + 120000) / 2 / 2080 ≈ 48.08
    assert 45 <= est["hourly_rate_usd"] <= 50


def test_velocity_returns_none_when_no_pay_info():
    job = {"jd_text": "We're a great place to work!", "comp": "", "discovery": {}}
    est = vel.estimate(job)
    assert est["hourly_rate_usd"] is None
    assert est["weekly_est_usd"] is None
    assert est["velocity_score"] is None


def test_velocity_part_time_signal_halves_hours():
    job = {"jd_text": "$20/hr part-time position", "comp": "",
           "discovery": {"employment_type": "part-time"}}
    est = vel.estimate(job)
    assert est["hourly_rate_usd"] == 20.0
    assert est["hours_per_week"] == 20
    assert est["weekly_est_usd"] == 400.0


def test_velocity_decays_with_posting_age():
    posted_recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    posted_stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fresh = vel.estimate({"jd_text": "$25/hr", "comp": "",
                            "discovery": {"posted_at": posted_recent}})
    stale = vel.estimate({"jd_text": "$25/hr", "comp": "",
                            "discovery": {"posted_at": posted_stale}})
    assert fresh["velocity_score"] > stale["velocity_score"]


# =====================================================================
# Employer cap — pure calc lives in check_cap but requires DB. We test
# the pure key normalization + math without hitting DB.
# =====================================================================
def test_employer_key_falls_back_to_company_name():
    assert cap._employer_key({"company_id": "abc"}) == "cid:abc"
    assert cap._employer_key({"company_name": "Lucid Motors"}) == "cn:lucid motors"
    assert cap._employer_key({"job_snapshot": {"company_name": "Waymo"}}) == "cn:waymo"
    assert cap._employer_key({}) is None


def test_employer_cap_constants():
    """Defaults surfaced via /dashboard/supply-reality — must match founder brief (3-per-30d)."""
    assert cap.EMPLOYER_CAP_PER_30D == 3
    assert cap.CAP_WINDOW_DAYS == 30


# =====================================================================
# Credential-to-Income catalog integrity.
# =====================================================================
def test_credentials_catalog_shape_and_integrity():
    catalog = get_catalog()
    assert len(catalog) >= 9
    seen_ids = set()
    for row in catalog:
        # Structural invariants
        for k in ("id", "label", "kind", "mandatory", "typical_hourly",
                  "time_to_credential", "approx_cost_usd", "suggested_next", "notes"):
            assert k in row, f"missing key {k} in {row.get('id')}"
        assert row["id"] not in seen_ids, f"duplicate id {row['id']}"
        seen_ids.add(row["id"])
        assert row["kind"] in ("certification", "license", "permit", "training")
        # Typical hourly range is monotonic
        th = row["typical_hourly"]
        assert th["low"] <= th["median"] <= th["high"]
        # Cost floor >= 0
        assert row["approx_cost_usd"]["low"] >= 0


def test_credentials_by_id_returns_matching_row_or_none():
    assert by_id("cdl-class-a")["id"] == "cdl-class-a"
    assert by_id("does-not-exist") is None


# =====================================================================
# Gate-engine notes propagation — evaluate() must expose a `notes` list.
# =====================================================================
def test_evaluate_returns_notes_list():
    job = {
        "id": "j1", "canonical_key": "x::1", "title": "Any", "status": "live",
        "last_verified": datetime.now(timezone.utc),
        "eligibility_requirements": {}, "requirements": {"degree_level": "PhD"},
    }
    ctx = {"user_id": "u", "eligibility": {"status": "citizen"}, "preferences": {},
           "approved_skills": set(), "approved_education": [{"degree": "BS"}],
           "approved_employment": [], "approved_certifications": [],
           "existing_applications": set(), "hidden_job_ids": set()}
    res = gate_engine.evaluate(ctx, job)
    assert "notes" in res
    assert isinstance(res["notes"], list)
    # The degree note must be present
    edu_notes = [n for n in res["notes"] if n["gate"] == "education_requirement"]
    assert edu_notes
    assert "PhD" in edu_notes[0]["note"]

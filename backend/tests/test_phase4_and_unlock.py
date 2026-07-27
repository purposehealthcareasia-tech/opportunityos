"""Phase 4 (items 2–6) + credential-unlock — unit tests (no DB).

Covers:
  * credential_unlock catalog regex integrity
  * email_route dedup key math
  * bulk_prep cost per-model default calc
  * submit_sprint fixture guardrails (rejects non-fixture jobs / non-fixture users)
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services import credential_unlock as unlock_svc
from domains.email_route import _dedup_key
from domains.bulk_prep import _cost_for_generation
from domains.submit_sprint import (
    _assert_fixture_user, _assert_fixture_job, FIXTURE_EMAILS,
)


# =====================================================================
# credential_unlock — regexes must cover every catalog row
# =====================================================================
def test_unlock_catalog_regex_coverage():
    from domains.credentials import get_catalog
    ids = {r["id"] for r in get_catalog()}
    assert set(unlock_svc._CATALOG_REGEXES.keys()) == ids, \
        "Every catalog credential must have an unlock regex."


def test_unlock_regex_matches_common_jd_phrasings():
    import re
    cases = [
        ("cdl-class-a", "Requires a valid CDL Class A license."),
        ("cna", "Certified Nursing Assistant (CNA) certification required."),
        ("emt-basic", "EMT-B certification through NREMT."),
        ("forklift-osha", "Forklift certification per OSHA 29 CFR 1910.178."),
        ("food-handler-az", "Must obtain a food handler card within 30 days."),
        ("az-fingerprint-clearance", "Level 1 fingerprint clearance required."),
        ("guard-card-az", "Unarmed security guard license (guard card)."),
    ]
    for cred_id, jd in cases:
        pat = unlock_svc._CATALOG_REGEXES[cred_id]
        assert re.search(pat, jd, re.IGNORECASE), (
            f"regex for {cred_id!r} failed on: {jd!r}"
        )


# =====================================================================
# email_route — dedup key is deterministic and case-insensitive
# =====================================================================
def test_dedup_key_case_insensitive_destination():
    a = _dedup_key("u1", "app1", "HR@Company.com")
    b = _dedup_key("u1", "app1", "hr@company.com")
    c = _dedup_key("u1", "app1", "  hr@company.com  ")
    d = _dedup_key("u1", "app1", "hr@different.com")
    assert a == b == c
    assert a != d


def test_dedup_key_varies_with_user_and_app():
    assert _dedup_key("u1", "app1", "hr@x.com") != _dedup_key("u2", "app1", "hr@x.com")
    assert _dedup_key("u1", "app1", "hr@x.com") != _dedup_key("u1", "app2", "hr@x.com")


# =====================================================================
# bulk_prep — cost per-model defaults never crash on empty rows
# =====================================================================
def test_cost_for_generation_uses_recorded_cost_when_present():
    gen = {"cost_usd": 0.037, "tokens_in": 1000, "tokens_out": 500,
           "model": "claude-sonnet-4.5"}
    assert _cost_for_generation(gen) == pytest.approx(0.037)


def test_cost_for_generation_fallback_by_model():
    gen = {"tokens_in": 1000, "tokens_out": 500, "model": "claude-sonnet-4.5"}
    # Sonnet defaults: 3/M in, 15/M out → 0.003 + 0.0075 = 0.0105
    assert _cost_for_generation(gen) == pytest.approx(0.0105)


def test_cost_for_generation_zero_when_empty():
    gen = {"tokens_in": 0, "tokens_out": 0, "model": "unknown"}
    assert _cost_for_generation(gen) == 0.0


def test_cost_for_generation_gemini_flash_is_cheap():
    gen = {"tokens_in": 1000, "tokens_out": 500, "model": "gemini-3-flash"}
    # Gemini flash defaults: 0.35/M in, 1.4/M out → 0.00035 + 0.0007 = 0.00105
    assert _cost_for_generation(gen) == pytest.approx(0.00105)


# =====================================================================
# submit_sprint — fixture guardrails
# =====================================================================
def test_sprint_rejects_non_fixture_user():
    with pytest.raises(HTTPException) as exc:
        _assert_fixture_user({"email": "attacker@example.com", "roles": []})
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "sprint_fixture_only"


def test_sprint_accepts_fixture_email():
    for email in FIXTURE_EMAILS:
        _assert_fixture_user({"email": email, "roles": []})  # must not raise


def test_sprint_accepts_sprint_operator_role():
    _assert_fixture_user({"email": "operator@example.com",
                           "roles": ["sprint_operator"]})


def test_sprint_rejects_non_fixture_job():
    row = {"id": "app1",
           "job_snapshot": {"company_name": "Real Employer LLC",
                              "is_sample": False}}
    with pytest.raises(HTTPException) as exc:
        _assert_fixture_job(row)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "sprint_not_fixture_job"


def test_sprint_accepts_sample_job():
    row = {"id": "app1",
           "job_snapshot": {"company_name": "SampleCo (demo)",
                              "is_sample": True}}
    _assert_fixture_job(row)  # must not raise

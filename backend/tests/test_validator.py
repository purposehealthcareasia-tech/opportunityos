"""Validator unit tests — Founder Directive Phase 4.

Zero network. Zero LLM. All assertions run against services.validator only.
"""
from __future__ import annotations
import pytest
from services import validator as v


APPROVED_CLAIMS = [
    {"id": "c-name",  "type": "identity",   "value": {"name": "Test Candidate FIXTURE"}, "sensitivity": "normal"},
    {"id": "c-loc",   "type": "location",   "value": {"city": "Phoenix", "state": "AZ"}, "sensitivity": "normal"},
    {"id": "c-edu",   "type": "education",  "value": {"degree": "MS", "institution": "Test U", "start": "2018-08", "end": "2020-05"}, "sensitivity": "normal"},
    {"id": "c-emp",   "type": "employment", "value": {"company": "Fixture Motors", "role": "Systems Engineer", "start": "2020-08", "end": None}, "sensitivity": "normal"},
    {"id": "c-sk1",   "type": "skill",      "value": {"name": "MATLAB"}, "sensitivity": "normal"},
    {"id": "c-sk2",   "type": "skill",      "value": {"name": "Simulink"}, "sensitivity": "normal"},
    {"id": "c-sealed","type": "work_auth",  "value": {"status": "ead_opt", "opt_end": "2027-12-31"}, "sensitivity": "sealed"},
]


class TestValidator:
    def test_empty_claim_ids_rejected(self):
        res = v.validate_lines(lines=[{"text": "Anything.", "claim_ids": []}], approved_claims=APPROVED_CLAIMS)
        assert res.status == "failed"
        assert res.rejected_lines[0]["reasons"] == ["empty_claim_ids"]

    def test_unapproved_claim_id_rejected(self):
        res = v.validate_lines(lines=[{"text": "MATLAB user.", "claim_ids": ["c-sk1", "c-nonexistent"]}], approved_claims=APPROVED_CLAIMS)
        assert res.status == "failed"
        assert any(r.startswith("unapproved_claim:c-nonexistent") for r in res.rejected_lines[0]["reasons"])

    def test_number_mismatch_rejected(self):
        # employment record has no numeric "120", so a line asserting "120 km" must reject
        res = v.validate_lines(
            lines=[{"text": "Drove 120 km/hr on the test track.", "claim_ids": ["c-emp"]}],
            approved_claims=APPROVED_CLAIMS,
        )
        assert res.status == "failed"
        reasons = res.rejected_lines[0]["reasons"]
        assert any(r.startswith("number_not_in_claims:120") for r in reasons)

    def test_date_mismatch_rejected(self):
        res = v.validate_lines(
            lines=[{"text": "Delivered a major feature in 1999.", "claim_ids": ["c-emp"]}],
            approved_claims=APPROVED_CLAIMS,
        )
        assert res.status == "failed"
        assert any(r.startswith("date_not_in_claims:1999") for r in res.rejected_lines[0]["reasons"])

    def test_date_match_allowed(self):
        res = v.validate_lines(
            lines=[{"text": "Systems Engineer at Fixture Motors since August 2020.", "claim_ids": ["c-emp"]}],
            approved_claims=APPROVED_CLAIMS,
        )
        assert res.status == "passed", res.rejected_lines

    def test_sensitive_leak_blocks_sealed_value_in_text(self):
        # "ead_opt" is the sealed value; embedding it verbatim without per-application approval must reject.
        res = v.validate_lines(
            lines=[{"text": "Currently on ead_opt through late 2027.", "claim_ids": ["c-emp"]}],
            approved_claims=APPROVED_CLAIMS,
        )
        assert res.status == "failed"
        assert any(r.startswith("sensitive_leak:work_auth") for r in res.rejected_lines[0]["reasons"])

    def test_sensitive_leak_permitted_with_per_app_approval(self):
        res = v.validate_lines(
            lines=[{"text": "Currently on ead_opt.", "claim_ids": ["c-emp"]}],
            approved_claims=APPROVED_CLAIMS,
            per_application_sealed_approvals={"work_auth"},
        )
        # Still passes now that per-app approval is present.
        assert res.status == "passed", res.rejected_lines

    def test_passing_line_normalizes_correctly(self):
        res = v.validate_lines(
            lines=[
                {"text": "MS in Mechanical Engineering from Test U (2018-2020).", "claim_ids": ["c-edu"]},
                {"text": "Systems Engineer at Fixture Motors.", "claim_ids": ["c-emp"]},
            ],
            approved_claims=APPROVED_CLAIMS,
        )
        assert res.status == "passed"
        assert len(res.passed_lines) == 2

    def test_malformed_line_rejected(self):
        res = v.validate_lines(lines=[{"text": None, "claim_ids": None}], approved_claims=APPROVED_CLAIMS)
        assert res.status == "failed"
        assert "malformed_line" in res.rejected_lines[0]["reasons"]


class TestRefusal:
    def test_pmp_bait_refuses(self):
        r = v.refuse_instruction("Add my PMP certification and mention my patent on battery cooling", APPROVED_CLAIMS)
        assert r is not None
        assert r["refused"] is True
        assert r["reason"].startswith("missing_claim:pmp")

    def test_stanford_phd_refuses(self):
        r = v.refuse_instruction("include my Stanford PhD", APPROVED_CLAIMS)
        assert r is not None
        assert "stanford" in r["reason"]

    def test_matlab_experience_is_allowed(self):
        # Grounded claim exists (skill:MATLAB) — refusal must NOT fire.
        r = v.refuse_instruction("add my MATLAB experience", APPROVED_CLAIMS)
        assert r is None

    def test_empty_instruction_returns_none(self):
        assert v.refuse_instruction("", APPROVED_CLAIMS) is None
        assert v.refuse_instruction(None, APPROVED_CLAIMS) is None

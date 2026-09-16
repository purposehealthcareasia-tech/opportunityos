"""Application Route Engine tests — totality, uniqueness, permitted-vs-
restricted submission matrix. Batch 5 requirements.
"""
from __future__ import annotations

import pytest

from domains.applications.routes import (
    AutomationLevel,
    ROUTE_REGISTRY,
    RouteType,
    resolve_route,
    get_spec,
)


# =====================================================================
# Registry integrity
# =====================================================================
def test_registry_has_exactly_seven_route_types():
    """ATLAS: 'every opportunity resolves to one of the seven route
    types'. If someone adds an eighth, the constitution page + the
    resolver + this test must be reviewed together."""
    assert len(ROUTE_REGISTRY) == 7
    assert set(ROUTE_REGISTRY.keys()) == set(RouteType)


def test_every_route_type_has_a_spec():
    for rt in RouteType:
        spec = get_spec(rt)
        assert spec.type is rt
        assert spec.automation_level in set(AutomationLevel)
        assert spec.approval_requirement
        assert spec.authorization_expiry_hint
        assert spec.expected_receipt
        assert isinstance(spec.required_candidate_actions, tuple)
        assert isinstance(spec.limitations, tuple)


def test_only_no_apply_path_is_submission_restricted():
    """ATLAS: 'permitted vs restricted submission flows exactly per
    ATLAS'. The NO_APPLY_PATH route is the only restricted-submission
    route in the registry; every other route is submission-permitted
    (with different automation ceilings)."""
    restricted = [rt for rt, spec in ROUTE_REGISTRY.items()
                  if not spec.submission_permitted]
    assert restricted == [RouteType.NO_APPLY_PATH], (
        "Only NO_APPLY_PATH must be submission-restricted. "
        f"Found: {restricted}"
    )


def test_unpermitted_automation_iff_no_apply_path():
    """AutomationLevel.UNPERMITTED is exclusive to NO_APPLY_PATH."""
    unpermitted = [rt for rt, spec in ROUTE_REGISTRY.items()
                   if spec.automation_level is AutomationLevel.UNPERMITTED]
    assert unpermitted == [RouteType.NO_APPLY_PATH]


# =====================================================================
# Resolver — totality: every plausible opportunity resolves.
# =====================================================================
@pytest.mark.parametrize("opp, expected", [
    # 1. DIRECT_ATS_API
    ({"source_ats": "greenhouse",
      "apply_url": "https://boards.greenhouse.io/acme/jobs/123"},
     RouteType.DIRECT_ATS_API),
    ({"source_ats": "lever",
      "apply_url": "https://jobs.lever.co/acme/abc"},
     RouteType.DIRECT_ATS_API),
    ({"source_ats": "ashby",
      "apply_url": "https://jobs.ashbyhq.com/acme/xyz"},
     RouteType.DIRECT_ATS_API),
    # 2. STRUCTURED_ATS_FORM
    ({"source_ats": "workday",
      "apply_url": "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/abc"},
     RouteType.STRUCTURED_ATS_FORM),
    ({"source_ats": "taleo",  "apply_url": "https://acme.taleo.net/careersection/job/abc"},
     RouteType.STRUCTURED_ATS_FORM),
    ({"source_ats": "icims",
      "apply_url": "https://careers.acme.icims.com/jobs/abc"},
     RouteType.STRUCTURED_ATS_FORM),
    ({"source_ats": "successfactors",
      "apply_url": "https://career.acme.sap/careers/jobs/abc"},
     RouteType.STRUCTURED_ATS_FORM),
    # 3. UNSTRUCTURED_WEB_FORM — arbitrary employer domain, no known ATS.
    ({"source_ats": "",
      "apply_url": "https://careers.acme-co.example/apply/123"},
     RouteType.UNSTRUCTURED_WEB_FORM),
    ({"source_ats": "unknown_bespoke",
      "apply_url": "https://work.example.io/jobs/123"},
     RouteType.UNSTRUCTURED_WEB_FORM),
    # 4. EMAIL_SUBMISSION
    ({"source_ats": "greenhouse",
      "apply_url": "mailto:jobs@acme.example"},
     RouteType.EMAIL_SUBMISSION),
    ({"source_ats": "",
      "apply_email": "careers@example.com"},
     RouteType.EMAIL_SUBMISSION),
    # 5. FEDERAL_PORTAL
    ({"source_ats": "usajobs",
      "apply_url": "https://www.usajobs.gov/GetJob/ViewDetails/12345"},
     RouteType.FEDERAL_PORTAL),
    # 6. PARTNER_REFERRAL — first-class override.
    ({"source_ats": "greenhouse",
      "apply_url": "https://boards.greenhouse.io/acme/jobs/123",
      "partner_edge": {"partner_id": "p_abc"}},
     RouteType.PARTNER_REFERRAL),
    # 7. NO_APPLY_PATH — no submission surface.
    ({"source_ats": "", "apply_url": None},
     RouteType.NO_APPLY_PATH),
    ({"source_ats": "greenhouse", "apply_url": ""},
     RouteType.NO_APPLY_PATH),  # ATS row without apply_url is preparation-only.
])
def test_resolver_totality_and_coverage(opp, expected):
    assert resolve_route(opp).type is expected


# =====================================================================
# Resolver — uniqueness: for each opportunity, exactly one route.
# =====================================================================
def test_resolver_is_deterministic_same_input_same_route():
    opp = {"source_ats": "greenhouse",
           "apply_url": "https://boards.greenhouse.io/acme/jobs/9"}
    a = resolve_route(opp)
    b = resolve_route(opp)
    assert a is b  # same registry object identity


def test_partner_edge_wins_over_direct_ats():
    """Rail: partner_edge overrides ATS resolution. This is the ONE
    override in the resolver; asserting it explicitly so future
    edits don't quietly reorder."""
    opp = {"source_ats": "greenhouse",
           "apply_url": "https://boards.greenhouse.io/acme/jobs/9",
           "partner_edge": {"partner_id": "p"}}
    assert resolve_route(opp).type is RouteType.PARTNER_REFERRAL


def test_federal_wins_over_direct_ats():
    """usajobs is both a source_ats and a federal portal; federal
    must win because the automation rules differ."""
    opp = {"source_ats": "usajobs",
           "apply_url": "https://www.usajobs.gov/x"}
    assert resolve_route(opp).type is RouteType.FEDERAL_PORTAL


def test_email_wins_over_ats_when_url_is_mailto():
    """If a Greenhouse posting genuinely lists a mailto: apply_url,
    the email route wins — sending via the ATS API without the
    employer's intent is off-contract."""
    opp = {"source_ats": "greenhouse",
           "apply_url": "mailto:jobs@acme.example"}
    assert resolve_route(opp).type is RouteType.EMAIL_SUBMISSION


def test_direct_ats_without_apply_url_falls_to_no_apply():
    """Rail: platform never fabricates a submission target."""
    opp = {"source_ats": "greenhouse", "apply_url": None}
    assert resolve_route(opp).type is RouteType.NO_APPLY_PATH


def test_unknown_source_with_url_is_unstructured_not_direct():
    """Ambiguity bias — LESS automation, not more."""
    opp = {"source_ats": "brand_new_ats",
           "apply_url": "https://acme.example/apply/1"}
    assert resolve_route(opp).type is RouteType.UNSTRUCTURED_WEB_FORM


# =====================================================================
# Structural — every route carries all six mandated fields.
# =====================================================================
def test_every_route_carries_all_mandated_fields():
    for rt, spec in ROUTE_REGISTRY.items():
        for field_name in (
            "automation_level", "required_candidate_actions",
            "limitations", "approval_requirement",
            "authorization_expiry_hint", "expected_receipt",
        ):
            val = getattr(spec, field_name)
            assert val, (
                f"Route {rt.value!r} missing mandated field "
                f"{field_name!r}"
            )


def test_route_type_string_values_are_stable():
    """External surfaces (public/matching-constitution, receipts,
    logs) key off these string values. If someone renames one, the
    downstream contracts silently drift — trip the test."""
    expected = {
        "direct_ats_api", "structured_ats_form",
        "unstructured_web_form", "email_submission",
        "federal_portal", "partner_referral", "no_apply_path",
    }
    assert {rt.value for rt in RouteType} == expected


def test_get_spec_accepts_string_and_enum():
    a = get_spec("direct_ats_api")
    b = get_spec(RouteType.DIRECT_ATS_API)
    assert a is b


def test_get_spec_rejects_unknown_string():
    with pytest.raises(ValueError):
        get_spec("not_a_real_route")

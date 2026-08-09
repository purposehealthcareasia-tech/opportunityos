"""Consent scope enum integrity — regression guard.

This guard prevents the "consent scope drift" bug class that has now
appeared TWICE:

  * Phase 4 (2026-07-27): `submit_applications` was added to
    `core/policy.py::CONSENT_SCOPES` but the API-layer `ScopeName`
    Literal in `domains/consent/models.py` was not updated, so
    `POST /api/v1/consents {scope: "submit_applications"}` 422'd.
  * Phase 5 Gate A (2026-08-09): SAME class of bug repeated —
    `share_passport`, `interview_prep_generate`, `passport_api_access`
    were added to `CONSENT_SCOPES` for 5a/5d/5i but the API validator
    rejected them at grant time, permanently locking users out of the
    feature after any revoke.

STRUCTURAL FIX (this pass): `domains/consent/models.py::ScopeName` is
now typed as `str` with a Pydantic `field_validator` that reads
`core.policy.SCOPE_KEYS` at model-validation time. There is no longer
a second source of truth. The guards below lock that invariant.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.policy import SCOPE_KEYS
from domains.consent.models import ConsentChangeRequest


REQUIRE_CONSENT_RX = re.compile(r'require_consent\(\s*["\']([a-z_]+)["\']\s*\)')


def _scan_backend_for_scopes() -> set[str]:
    root = Path("/app/backend")
    scopes: set[str] = set()
    for py in root.rglob("*.py"):
        if "tests" in py.parts or "__pycache__" in py.parts:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in REQUIRE_CONSENT_RX.finditer(text):
            scopes.add(m.group(1))
    return scopes


# --------------------------------------------------------------- guard 1
def test_every_route_gating_scope_is_in_enum():
    """A route may only gate on a scope the user is allowed to grant."""
    used = _scan_backend_for_scopes()
    missing = sorted(used - SCOPE_KEYS)
    assert not missing, (
        f"require_consent(...) referenced scope(s) NOT in CONSENT_SCOPES: {missing}. "
        f"Enum currently: {sorted(SCOPE_KEYS)}"
    )


def test_submit_applications_scope_exists():
    """Phase 4 (Founder Brief) — batch-authorization scope must exist."""
    assert "submit_applications" in SCOPE_KEYS


def test_scope_enum_is_a_superset_of_expected_five_plus_one():
    """Regression: ensure we didn't accidentally shrink the enum."""
    expected = {"process_career_data", "discover_jobs", "generate_materials",
                "track_applications", "email_me", "submit_applications"}
    assert expected.issubset(SCOPE_KEYS)


# --------------------------------------------------------------- guard 2 (NEW)
def test_api_validator_accepts_every_scope_in_the_enum():
    """STRUCTURAL LOCK: for every scope in `CONSENT_SCOPES`, a
    `ConsentChangeRequest {scope: <name>, granted: true, ...}` MUST
    validate cleanly. This is what the old guard MISSED — it only
    scanned route gates, never the grant path itself.

    If someone adds a scope to `CONSENT_SCOPES` but the API validator
    (Pydantic `ScopeName` field) rejects it, users are locked out —
    they can be REQUIRED to hold a scope they cannot GRANT. This
    test fails immediately in that case.
    """
    failures: list[tuple[str, str]] = []
    for scope in sorted(SCOPE_KEYS):
        try:
            ConsentChangeRequest(
                scope=scope, granted=True, policy_text_version="1.0",
            )
        except ValidationError as e:
            failures.append((scope, str(e)))
    assert not failures, (
        "API validator refuses scope(s) that are in CONSENT_SCOPES:\n"
        + "\n".join(f"  - {s}: {msg[:120]}" for s, msg in failures)
    )


def test_api_validator_rejects_unknown_scope():
    """Complementary lock: the validator MUST refuse a scope that is
    NOT in `CONSENT_SCOPES`. This is what protects downstream code
    from a rogue-string payload."""
    with pytest.raises(ValidationError) as ei:
        ConsentChangeRequest(
            scope="rogue_scope_that_does_not_exist",
            granted=True, policy_text_version="1.0",
        )
    msg = str(ei.value).lower()
    assert "unknown consent scope" in msg or "unknown" in msg


# --------------------------------------------------------------- guard 3 (NEW)
def test_phase5_scopes_are_registered():
    """Explicit lock for Gate A · FAIL 3 — the specific scopes that
    regressed. Adding a test line per NEW scope on each phase costs
    ~1 line and prevents this class of bug from silently returning."""
    for scope in ("share_passport", "interview_prep_generate", "passport_api_access"):
        assert scope in SCOPE_KEYS, (
            f"Phase 5 scope '{scope}' missing from CONSENT_SCOPES — "
            f"add it to core/policy.py::CONSENT_SCOPES."
        )
        ConsentChangeRequest(
            scope=scope, granted=True, policy_text_version="1.0",
        )  # must not raise


# --------------------------------------------------------------- guard 4 (NEW)
def test_scope_name_is_not_a_hardcoded_literal():
    """STRUCTURAL LOCK: `ScopeName` must not be a hardcoded
    `Literal[...]`. Using a Literal creates a second source of truth
    (the type) that MUST be manually kept in sync with the runtime
    enum. This has now caused the same class of bug twice. Failing
    this test forces the fix at the source, not at the symptom."""
    import typing
    from domains.consent import models
    scope_type = getattr(models, "ScopeName")
    origin = typing.get_origin(scope_type)
    # Accept either `str` (correct) or a validator-based custom type,
    # but NOT `Literal[...]`.
    assert origin is not typing.Literal, (
        "domains/consent/models.py::ScopeName must NOT be a hardcoded "
        "`Literal[...]` — it forks from core.policy.CONSENT_SCOPES the "
        "moment a new scope is added. Use a `str` field + Pydantic "
        "validator that reads `SCOPE_KEYS` at validation time."
    )

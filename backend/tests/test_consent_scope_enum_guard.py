"""Consent scope enum integrity — Phase 4 regression guard (2026-07-27).

Every scope name referenced by `require_consent(...)` in the API surface
MUST also appear in `core.policy.CONSENT_SCOPES`. Otherwise the endpoint
becomes structurally unreachable (users cannot grant a scope the enum
doesn't accept). This test scans every backend/domains/*.py file for
`require_consent("<name>")` and asserts each <name> is in the enum.

Founder mandate: batch-authorization scope `submit_applications` was
missing pre-2026-07-27 fix. This test prevents recurrence.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.policy import SCOPE_KEYS


REQUIRE_CONSENT_RX = re.compile(r'require_consent\(\s*["\']([a-z_]+)["\']\s*\)')


def _scan_backend_for_scopes() -> set[str]:
    root = Path("/app/backend")
    scopes: set[str] = set()
    for py in root.rglob("*.py"):
        # Skip tests + third-party
        if "tests" in py.parts or "__pycache__" in py.parts:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in REQUIRE_CONSENT_RX.finditer(text):
            scopes.add(m.group(1))
    return scopes


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

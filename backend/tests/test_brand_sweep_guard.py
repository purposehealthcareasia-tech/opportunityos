"""P0 Truth Audit (b) — brand sweep guard.

Fails CI if any user-facing served surface reintroduces the legacy
`opportunityos.dev` / `opportunityos.example` / `opportunityos-export`
brand. Internal-only strings (fixture user emails in allowlists, DB
name, storage prefix, dev-facing comments/docstrings) are explicitly
allowlisted below with a rationale each.
"""
from __future__ import annotations

import pathlib
import re

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
BACKEND_DOMAINS = REPO_ROOT / "backend" / "domains"
BACKEND_SERVICES = REPO_ROOT / "backend" / "services"


# Substrings that would indicate a user-facing brand leak.
FORBIDDEN_PATTERNS = [
    r"opportunityos\.dev",
    r"opportunityos\.example",
    r"opportunityos-export",
]

# Files/paths that legitimately reference these substrings for internal
# purposes (fixture allowlists, seeder tokens, comments explaining the
# rebrand). Each entry MUST carry a rationale in the value.
ALLOWLIST = {
    "backend/domains/standards/metrics.py":
        "FIXTURE_EMAILS constant — hardcoded list of fixture user emails "
        "used to EXCLUDE those users from every public /standards metric. "
        "The strings must equal what the seeder writes, so referencing them "
        "here is internal exclusion machinery, not user-facing branding.",
    "backend/domains/fixtures/internal_router.py":
        "Internal-only endpoint gated by X-Service-Token; docstring + response "
        "'note' field name the stable fixture user email as an ID, not as user-"
        "facing branding.",
    # Fixture user allowlists — email addresses are stable IDs baked into
    # the seeder + test_credentials.md; changing them would invalidate
    # every existing fixture. Rebrand rail said "user-visible strings only".
    "frontend/src/pages/SubmitSprint.jsx":
        "Fixture user allowlist — fixture-ead@ / fixture-admin@ are stable IDs, "
        "not user-facing branding.",
    "backend/domains/submit_sprint/__init__.py":
        "Fixture user allowlist — same stable-ID rationale as SubmitSprint.jsx.",
    "frontend/src/lib/consentScopes.js":
        "Handles legacy backend-returned brand strings via regex — INTENTIONALLY "
        "references the old brand to defensively rewrite it on the client.",
}


def _iter_files():
    for root in (FRONTEND_SRC, BACKEND_DOMAINS, BACKEND_SERVICES):
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in {".js", ".jsx", ".ts", ".tsx", ".py"}:
                continue
            # Never scan tests/, seeds/, or __pycache__.
            parts = set(p.parts)
            if "__pycache__" in parts or "tests" in parts or "seeds" in parts:
                continue
            yield p


def test_no_user_facing_opportunityos_leak():
    hits = []
    for p in _iter_files():
        rel = str(p.relative_to(REPO_ROOT))
        if rel in ALLOWLIST:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in FORBIDDEN_PATTERNS:
            for m in re.finditer(pat, text):
                # Compute 1-based line number.
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{rel}:{line}  matched {pat!r}")
    assert not hits, (
        "user-facing brand leak (opportunityos.dev / .example / -export) "
        "detected in served surfaces:\n  " + "\n  ".join(hits) +
        "\n\nIf the reference is legitimately internal, add its path to the "
        "ALLOWLIST in this test with a rationale."
    )

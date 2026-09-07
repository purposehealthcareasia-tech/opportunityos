"""P0 Truth Audit WARN fix (2026-08-13) — /privacy-policy serves REAL
static policy content at the HTTP layer, no SPA shell in the redirect
chain.

Founder gate result: 4/4 PASS with ONE WARN — the SPA-level
window.location.replace fix from commit 8249bd73 fired AFTER JS ran,
so a curl request landed on the SPA shell. The fix here is a physical
file at frontend/public/privacy-policy/index.html (copy of privacy.html)
that the static-file server returns BEFORE the SPA fallback. A curl
with -L (follow redirects) lands on the real 14KB versioned policy
document, no SPA index.html in the chain.

Test strategy: static-file assertion (the physical file exists and
carries the same policy identity markers as privacy.html) + live curl
guard (fetches the deployed URL WITH follow-redirects, asserts the
final body contains the policy heading + Version 1.0, and its
content-type is text/html).
"""
from __future__ import annotations

import os
import pathlib
import subprocess

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"


def test_static_privacy_policy_directory_index_exists():
    """The physical index.html under /privacy-policy/ must exist so the
    static-file server returns it directly (no SPA fallthrough)."""
    p = PUBLIC / "privacy-policy" / "index.html"
    assert p.exists(), (
        "frontend/public/privacy-policy/index.html must exist so the "
        "static server returns the real policy at /privacy-policy(/) "
        "BEFORE the SPA fallback (avoids serving the React shell)."
    )
    text = p.read_text(encoding="utf-8")
    assert "Privacy Policy" in text, "static /privacy-policy/index.html must contain the policy heading"
    assert "Version" in text and "1.0" in text, (
        "static /privacy-policy/index.html must carry the explicit policy version"
    )
    assert "opportunityos" not in text.lower(), (
        "static /privacy-policy/index.html must not carry legacy OpportunityOS branding"
    )


def test_static_privacy_policy_matches_canonical_privacy_html():
    """The /privacy-policy/index.html file must be IDENTICAL to
    /privacy.html so version bumps stay in one place. Diff between them
    should be structurally zero — same policy, two paths."""
    canonical = (PUBLIC / "privacy.html").read_text(encoding="utf-8")
    mirror = (PUBLIC / "privacy-policy" / "index.html").read_text(encoding="utf-8")
    assert canonical == mirror, (
        "privacy.html and privacy-policy/index.html must be byte-identical; "
        "version bumps must edit privacy.html and cp -> privacy-policy/index.html."
    )


@pytest.mark.skipif(
    not os.environ.get("REACT_APP_BACKEND_URL"),
    reason="Requires REACT_APP_BACKEND_URL for live HTTP-layer verification",
)
def test_live_privacy_policy_curl_lands_on_real_body_not_spa_shell():
    """Live curl -L /privacy-policy MUST land on a body containing the
    policy heading + 'Version 1.0'. If the body still looks like the
    SPA shell (contains '<div id="root">' AND '<title>Fynd</title>' but
    NOT 'Privacy Policy'), the fix regressed."""
    base = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
    # -L follows redirects. -sS silent w/ errors. -o writes body. -w prints stats.
    result = subprocess.run(
        ["curl", "-sSL",
         f"{base}/privacy-policy",
         "-o", "/tmp/privacy_policy_curl_body.html",
         "-w", "%{http_code} %{content_type} %{size_download} %{num_redirects}"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, f"curl failed: {result.stderr!r}"
    stats = result.stdout.strip().split()
    http_code = int(stats[0])
    content_type = stats[1] if len(stats) >= 2 else ""
    size = int(stats[-2])
    redirects = int(stats[-1])
    assert http_code == 200, f"final http {http_code}"
    assert content_type.startswith("text/html"), f"content-type {content_type!r}"
    # SPA shell is <5KB; real policy is ~13-15KB.
    assert size >= 8000, f"body {size} bytes — too small; probably SPA shell"
    body = pathlib.Path("/tmp/privacy_policy_curl_body.html").read_text(
        encoding="utf-8", errors="ignore"
    )
    # Positive assertions — real policy markers.
    assert "Privacy Policy" in body, "body missing 'Privacy Policy' heading — SPA shell?"
    assert "1.0" in body, "body missing 'Version 1.0' marker"
    assert "Fynd" in body
    # Negative assertion — SPA shell markers.
    # If the SPA shell were served, the body would still contain '<div id="root">'
    # but NOT the policy §1/§2/… markers.
    for marker in ("<div id=\"root\">", "<div id='root'>"):
        if marker in body:
            # SPA shell would have this; real policy would also embed React's
            # dev-server injected refresh scripts. Check that the policy §
            # markers are ALSO present — that would prove the real doc.
            assert "Who we are" in body or "Who operates" in body, (
                f"body contains SPA root div but no policy §1 heading; "
                f"looks like the SPA shell shadowed the static file (regression). "
                f"redirects={redirects}"
            )

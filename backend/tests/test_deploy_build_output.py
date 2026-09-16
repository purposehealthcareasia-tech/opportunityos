"""Build-output tests — Priority 2 deploy gap.

Two invariants asserted here:

  1. `frontend/build/pulse/network.html` MUST exist after
     `CI=true yarn build`. This catches the class of regressions
     where the Pulse static bundle silently drops out of the
     production build artifact.
  2. `_resolve_git_sha()` must return a non-fabricated value in
     every code path AND fall through to "unknown" when every
     source is missing. Enforces the honest-fallback contract in
     the deploy-safe SHA ladder.

These tests DO NOT run `yarn build` — that's slow. They assert:
  * The Pulse source files exist under `frontend/public/pulse/`
    (which is what CRA copies into `build/pulse/` during the build).
  * If a fresh build has run, `frontend/build/pulse/network.html`
    is present (skipped otherwise — the test suite is not the
    build).
"""
from __future__ import annotations

import os
import pathlib

import pytest


APP_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FE_ROOT = APP_ROOT / "frontend"


# =====================================================================
# 1. Pulse bundle survives the build pipeline
# =====================================================================
def test_pulse_source_files_present_in_frontend_public():
    """`frontend/public/pulse/` MUST contain the Pulse HTML/JS/CSS.
    CRA copies `public/*` into `build/*` at build time, so if this
    passes, `yarn build` will place them in `build/pulse/`."""
    pulse_dir = FE_ROOT / "public" / "pulse"
    assert pulse_dir.is_dir(), (
        f"Missing directory {pulse_dir}. Pulse assets live under "
        "`frontend/public/pulse/` so CRA copies them into `build/pulse/` "
        "automatically. If this directory disappears, prod loses the "
        "Pulse UI."
    )
    # Every file the Pulse HTML references at load time.
    required_files = [
        "network.html",
        "network.js",
        "network.css",
        "app.js",
        "collider.js",
        "collider-ui.js",
        "directions.js",
        "directions.css",
        "finish.css",
        "icons.js",
        "metallic-silver.css",
        "liquid-experience.css",
        "responsive-layout.css",
    ]
    missing = [f for f in required_files if not (pulse_dir / f).is_file()]
    assert not missing, (
        f"Missing Pulse asset(s) under {pulse_dir}: {missing}. "
        "Every file referenced by network.html at load time must be "
        "present or the prod page 404s pieces of the UI."
    )


def test_pulse_bundle_exists_in_build_if_build_ran():
    """If a fresh `CI=true yarn build` has been run, the Pulse
    bundle MUST have landed in `frontend/build/pulse/network.html`.
    This is the SPECIFIC production regression the founder called
    out. Skipped when no build artifact is present locally so the
    test suite is not conflated with the build step."""
    build_pulse_html = FE_ROOT / "build" / "pulse" / "network.html"
    if not (FE_ROOT / "build").is_dir():
        pytest.skip(
            "frontend/build/ not present — run `CI=true yarn build` "
            "before this test to exercise the invariant."
        )
    assert build_pulse_html.is_file(), (
        f"Missing {build_pulse_html} after build. The Pulse static "
        "bundle did not survive `yarn build`. Root cause is almost "
        "always that `frontend/public/pulse/` was removed or a "
        ".gitignore / .dockerignore rule now excludes it. Fix + "
        "rebuild before publishing."
    )
    body = build_pulse_html.read_text(encoding="utf-8", errors="ignore")
    # A trivial sanity check — the built html must reference at least
    # one of the pulse assets (network.js), NOT just be the SPA index.
    assert "network.js" in body or "pulse" in body.lower(), (
        f"{build_pulse_html} exists but appears to be the SPA shell "
        "(no reference to network.js / pulse). Something replaced the "
        "Pulse html at build time."
    )


# =====================================================================
# 2. Deploy-safe git_sha stamping — honest fallback preserved
# =====================================================================
def test_git_sha_resolver_prefers_env_var(monkeypatch, tmp_path):
    """GIT_SHA env var wins over every other source."""
    from server import _resolve_git_sha
    monkeypatch.setenv("GIT_SHA", "envdead0-envdead0")
    monkeypatch.delenv("BUILD_SHA", raising=False)
    sha = _resolve_git_sha()
    # Ladder truncates to 8 chars.
    assert sha == "envdead0"


def test_git_sha_resolver_falls_back_to_build_sha(monkeypatch):
    """BUILD_SHA is the legacy alias, still honored."""
    from server import _resolve_git_sha
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setenv("BUILD_SHA", "buildsha1")
    sha = _resolve_git_sha()
    assert sha == "buildsha"


def test_git_sha_resolver_reads_baked_file(monkeypatch, tmp_path):
    """When env vars are absent, the resolver reads /app/.git-sha."""
    from server import _resolve_git_sha
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILD_SHA", raising=False)
    sha_file = APP_ROOT / ".git-sha"
    if sha_file.is_file():
        content = sha_file.read_text(encoding="utf-8").strip()
        sha = _resolve_git_sha()
        # The baked value wins over `git rev-parse` (ladder order).
        # The resolver truncates to 8 chars.
        assert sha == content[:8]


def test_git_sha_resolver_returns_unknown_when_all_sources_missing(
    monkeypatch, tmp_path,
):
    """When every source fails, the resolver returns the string
    'unknown' — never a fabricated placeholder. Rehearses the
    prod-image case where .git/ is absent and the bake step was
    skipped."""
    from server import _resolve_git_sha
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILD_SHA", raising=False)
    # Hide /app/.git-sha and /app/.git by pointing at a scratch dir
    # via `is_file` shim on Path.
    import pathlib as _pl
    real_is_file = _pl.Path.is_file
    def _no_git_sha_file(self):
        if self.name == ".git-sha":
            return False
        return real_is_file(self)
    monkeypatch.setattr(_pl.Path, "is_file", _no_git_sha_file)
    # Force subprocess to fail without a real cwd.
    import subprocess as _sp
    real_check_output = _sp.check_output
    def _boom(*a, **kw):
        raise _sp.CalledProcessError(returncode=128, cmd=a[0])
    monkeypatch.setattr(_sp, "check_output", _boom)
    sha = _resolve_git_sha()
    assert sha == "unknown"


def test_meta_version_endpoint_shape():
    """The public endpoint payload MUST carry: version, git_sha,
    booted_at, source. Prevents drift on the contract external
    monitors depend on."""
    import server as _s
    bv = _s._BUILD_VERSION
    assert set(bv.keys()) >= {"version", "git_sha", "booted_at", "source"}
    # git_sha is a non-empty string (may be "unknown" — that's honest).
    assert isinstance(bv["git_sha"], str) and bv["git_sha"]

"""P0 Truth Audit (c) — /api/v1/meta/version derives from build."""
from __future__ import annotations

import json
import pathlib

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client_per_test():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


@pytest.mark.asyncio
async def test_meta_version_returns_package_json_version_not_literal():
    """The response `version` field MUST equal `frontend/package.json`
    `.version`. Fails hard if a code path ever hardcodes a literal
    like `v0.1`."""
    from server import version_meta

    resp = await version_meta()
    assert isinstance(resp, dict)
    assert "version" in resp
    # Never a stringified literal that starts with 'v'.
    assert not resp["version"].startswith("v"), (
        f"version must be semver ('X.Y.Z'), not 'v...': got {resp['version']!r}"
    )
    # Cross-check against package.json.
    pkg = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend" / "package.json"
    pkg_version = json.loads(pkg.read_text(encoding="utf-8"))["version"]
    assert resp["version"] == pkg_version, (
        f"backend version {resp['version']!r} != package.json version {pkg_version!r}"
    )


@pytest.mark.asyncio
async def test_meta_version_carries_git_sha_and_boot_time():
    from server import version_meta

    resp = await version_meta()
    assert "git_sha" in resp
    # 8-char short SHA or 'unknown' (unknown only if outside git repo, never in this pod).
    assert isinstance(resp["git_sha"], str) and (
        resp["git_sha"] == "unknown" or len(resp["git_sha"]) == 8
    )
    assert "booted_at" in resp
    # ISO-8601 with a TZ suffix (Z or +00:00) — never a naive timestamp.
    assert resp["booted_at"].endswith("+00:00") or resp["booted_at"].endswith("Z")
    assert resp.get("source") == "frontend/package.json"


def test_no_hardcoded_v01_footer_literal_in_landing_or_sidebar():
    """Static grep: neither Landing.jsx nor Sidebar.jsx may contain the
    literal 'v0.1' as a footer string. Founder rail: 'kill stale v0.1'."""
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    for rel in ("frontend/src/pages/Landing.jsx", "frontend/src/components/Sidebar.jsx"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "v0.1" not in text, (
            f"{rel} still contains 'v0.1' literal — footer must derive from build."
        )

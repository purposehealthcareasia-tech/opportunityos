"""Phase 3 regression tests.

Covers Founder-Directive compensating requirements:
- Unique-index proofs (canonical_key, submission_receipts, usage_meters)
- Atomic application state transitions (no race window)
- Gate engine parity between coverage-preview and feed
- Ingest auth semantics (401/403/503)
- 14-gate enumeration

Run:
    cd /app/backend && python3 -m pytest tests -v
"""
import os
import sys
from pathlib import Path

# So we can import `services.*`, `domains.*`, `core.*` from the /app/backend root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Founder Fix Round-2 · P0 #1 — autouse module-scope rebase.
# Every test file that mutates fixture-ead@ state gets its own clean baseline
# by calling /api/internal/fixture/rebase at module import time. This keeps
# the acceptance-check-B geometry (9/6, 4/2) reproducible even when the whole
# test suite runs in one pytest invocation.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402
import requests  # noqa: E402


BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")


def _service_token() -> str:
    with open("/app/backend/.env") as fh:
        for line in fh:
            if line.startswith("INTERNAL_SERVICE_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


# Test modules that hit the running preview backend against the fixture user.
_MODULES_NEEDING_REBASE = {
    "tests.test_fixture_acceptance_b",
    "tests.test_phase3_integration",
    "tests.test_round2_parity_rebase_feedback",
}


_TEST_ACCOUNT_EMAILS = (
    "fixture-ead@opportunityos.dev",
    "ujjwal@opportunityos.dev",
    "admin@opportunityos.dev",
    "support@opportunityos.dev",
)


def _clear_login_throttle_for_test_accounts():
    """Reset login-throttle buckets for known test accounts + purge any
    IP-bucket rows.

    SEC-P3(a) added a real per-identifier login throttle (10 attempts / 5 min)
    AND a per-IP throttle (30 attempts / 5 min). A full pytest sweep issues
    hundreds of auth-adjacent calls that would otherwise saturate BOTH buckets
    across the shared test runner IP. We purge the entire collection at every
    module boot — the dedicated `TestLoginThrottle` test uses unique random
    identifiers and reasserts the throttle in isolation.
    """
    try:
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "opportunityos")
        c = MongoClient(mongo_url, serverSelectionTimeoutMS=1500)
        c[db_name].login_throttle.delete_many({})
        c.close()
    except Exception as e:  # pragma: no cover — defensive, must not break tests
        print(f"[conftest] login_throttle purge skipped: {e}")


@pytest.fixture(autouse=True, scope="module")
def _rebase_before_each_module(request):
    """Rebase fixture-ead@ before every module in the allowlist runs its tests.

    Also always clears the login-throttle buckets for known test accounts
    (see `_clear_login_throttle_for_test_accounts`) so that a suite-wide run
    does not trip its own credential-stuffing guard.
    """
    _clear_login_throttle_for_test_accounts()
    mod_name = request.module.__name__ if request.module else ""
    if mod_name in _MODULES_NEEDING_REBASE:
        tok = _service_token()
        if tok:
            try:
                r = requests.post(
                    f"{BASE}/api/internal/fixture/rebase",
                    headers={"X-Service-Token": tok},
                    timeout=15,
                )
                # 200 is success; anything else we swallow so unit tests (which don't touch
                # the live backend at all) don't fail because the preview is temporarily down.
                if r.status_code != 200:
                    print(f"[conftest] fixture rebase for {mod_name} returned {r.status_code}: {r.text[:200]}")
            except Exception as e:
                print(f"[conftest] fixture rebase for {mod_name} raised: {e}")
    yield

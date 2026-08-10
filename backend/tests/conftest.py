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

# ---------------------------------------------------------------------------
# P2a · function-scope rebase — narrower whitelist (2026-08-10).
#
# Some individual tests inside otherwise-clean modules mutate fixture-ead@'s
# applications / application_outcomes / match_scores rows, then the NEXT
# test in the same suite run sees the accumulated state and fails with an
# unrelated assertion (classic cross-test pollution).
#
# Rather than a blanket autouse (which would mask real cross-test bugs AND
# break intentionally-ordered classes like
# test_fixture_acceptance_b::TestShortlistFlow whose test_02 depends on
# test_01's shortlist row still existing), we ship a precise whitelist by
# test node-id suffix. Each entry has an empirical justification below:
#   * Verified via: `curl /api/internal/fixture/rebase && pytest <one-test>`
#     passing solo but failing when run in-suite. Confirmed the failure
#     class is accumulation, NOT seed-drift.
# ---------------------------------------------------------------------------
_TESTS_NEEDING_FUNCTION_REBASE = {
    # Idempotency test asserts a fresh state-transition sequence starts from
    # a clean app row. Empirically verified: passes solo after rebase, fails
    # only when run in-suite where prior test files' shortlist calls linger.
    "tests/test_phase3_integration.py::test_idempotency_replay_on_state_transition",
    # Privacy-export hash-leak check reads /privacy/export which reflects
    # accumulated documents. Passes solo after rebase.
    "tests/test_milestone_a_integrations.py::TestRegressionSpotChecks::test_privacy_export_no_hash_leak",
    # test_match_score_and_feedback uses user_zero_token and seeds a
    # match_scores row after rebase. Feed cache holds stale IDs so the
    # subsequent /matches/for-job read may target a pre-rebase job.
    # P2a.3 rebase-then-fresh-compute ensures the read hits a live row.
    "tests/test_phase3_integration.py::test_match_score_and_feedback",
    # NOTE (2026-08-10): `test_receipts_immutability::test_supersedes_chain_
    # keeps_original_row` was investigated as a candidate — it fails in-suite
    # but the root cause is `RuntimeError: Event loop is closed` (motor +
    # asyncio.run() infra issue, same class as the 3 permanently-skipped
    # tests). Rebase does NOT help it; the fix was to reset
    # core.db._client / _db inside the test (see the test file itself,
    # not conftest). Filed as P2a.2.
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


# ---------------------------------------------------------------------------
# P2a · function-scope autouse (2026-08-10)
# ---------------------------------------------------------------------------
def _do_rebase(context: str) -> None:
    """Fire the live rebase endpoint. Swallow any error — a preview outage
    must never make a unit test fail with an infra symptom."""
    tok = _service_token()
    if not tok:
        return
    try:
        r = requests.post(
            f"{BASE}/api/internal/fixture/rebase",
            headers={"X-Service-Token": tok},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[conftest] fixture rebase (function-scope, {context}) returned {r.status_code}")
    except Exception as e:
        print(f"[conftest] fixture rebase (function-scope, {context}) raised: {e}")


@pytest.fixture(autouse=True, scope="function")
def _rebase_before_specific_tests(request):
    """Function-scope precise rebase for the accumulation-class tests
    empirically verified above (`_TESTS_NEEDING_FUNCTION_REBASE`).

    Tightly scoped by test node-id string suffix so this does NOT act as a
    blanket autouse. Intentionally-ordered classes (like
    test_fixture_acceptance_b::TestShortlistFlow whose test_02 depends on
    test_01's shortlist row still existing) will NEVER be entered here —
    only the specific pytest node-ids listed are matched.
    """
    node = request.node.nodeid
    for suffix in _TESTS_NEEDING_FUNCTION_REBASE:
        if node.endswith(suffix) or node == suffix:
            _do_rebase(f"node={suffix}")
            break
    yield

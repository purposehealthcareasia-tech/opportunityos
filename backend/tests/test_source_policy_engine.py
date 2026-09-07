"""P1 FOUNDATION Batch 1 · Source Access Policy Engine tests.

Locks the deterministic decision table, fail-closed defaults, kill
switch, and the invariant that NO LLM / string-substring logic is in
the policy path. Also validates every one of the 8 enumerated
operations against a compliant + a rejected source.
"""
from __future__ import annotations

import os
import pytest

from domains.source_policy import (
    Operation, PolicyDecision, PolicyDenied,
    RobotsStatus, TermsStatus, LicenseStatus, LegalReviewStatus,
    allow,
)


# ------------------------------------------------------------------
# Fixtures — canonical compliant + hostile source records
# ------------------------------------------------------------------
def _compliant() -> dict:
    return {
        "source_id": "greenhouse",
        "robotsStatus": RobotsStatus.RESPECTED.value,
        "termsStatus":  TermsStatus.COMPLIANT.value,
        "licenseStatus": LicenseStatus.NOT_APPLICABLE.value,
        "legalReviewStatus": LegalReviewStatus.APPROVED.value,
    }


def _hostile_terms() -> dict:
    r = _compliant()
    r["termsStatus"] = TermsStatus.HOSTILE.value
    return r


def _legal_pending() -> dict:
    r = _compliant()
    r["legalReviewStatus"] = LegalReviewStatus.PENDING.value
    return r


def _robots_blocked() -> dict:
    r = _compliant()
    r["robotsStatus"] = RobotsStatus.BLOCKED.value
    return r


# ------------------------------------------------------------------
# Structural
# ------------------------------------------------------------------
def test_four_status_fields_are_all_required():
    """Missing any of the 4 fields → fail-closed DENY (never ALLOW)."""
    for missing in ("robotsStatus", "termsStatus",
                    "licenseStatus", "legalReviewStatus"):
        record = _compliant()
        record.pop(missing)
        d = allow(source_record=record, operation=Operation.DISCOVER)
        assert not d.allowed, f"missing {missing} must fail-closed"
        assert "missing_or_invalid_status_fields" in d.reason


def test_all_eight_operations_are_enumerated():
    """No free-form op strings accepted; unknown op → DENY."""
    d = allow(source_record=_compliant(), operation="scrape_everything")
    assert not d.allowed
    assert "unknown_operation" in d.reason


# ------------------------------------------------------------------
# Compliant source — every enumerated op is ALLOWED (except where
# strict license is required by the row and license is NOT_APPLICABLE)
# ------------------------------------------------------------------
@pytest.mark.parametrize("op", [
    Operation.DISCOVER, Operation.FETCH, Operation.MONITOR,
    Operation.PAGINATE, Operation.PREPARE,
])
def test_compliant_source_permits_low_risk_ops(op):
    d = allow(source_record=_compliant(), operation=op)
    assert d.allowed, f"{op.value} should be allowed on a compliant source: {d.reason}"
    assert d.reason == "policy_permits_operation"


@pytest.mark.parametrize("op", [
    Operation.INTERACT, Operation.AUTHENTICATE, Operation.SUBMIT,
])
def test_compliant_but_unlicensed_denies_strict_ops(op):
    """Interact/authenticate/submit require LICENSED; NOT_APPLICABLE
    does NOT satisfy them (rail: strict license for high-risk ops).
    Compliant Greenhouse-style publisher source can DISCOVER/FETCH but
    can't INTERACT/SUBMIT unless it's LICENSED."""
    d = allow(source_record=_compliant(), operation=op)
    assert not d.allowed
    assert "license_status_not_in_permit_set" in d.reason \
           or "license_status_blocks_op" in d.reason


def test_licensed_source_permits_strict_ops():
    r = _compliant()
    r["licenseStatus"] = LicenseStatus.LICENSED.value
    for op in (Operation.INTERACT, Operation.AUTHENTICATE, Operation.SUBMIT):
        d = allow(source_record=r, operation=op)
        assert d.allowed, f"{op.value} should be allowed w/ LICENSED: {d.reason}"


# ------------------------------------------------------------------
# Denial paths
# ------------------------------------------------------------------
def test_robots_blocked_denies_every_op():
    for op in Operation:
        d = allow(source_record=_robots_blocked(), operation=op)
        assert not d.allowed, f"ROBOTS_BLOCKED must deny {op.value}: {d.reason}"


def test_hostile_terms_denies_every_op():
    for op in Operation:
        d = allow(source_record=_hostile_terms(), operation=op)
        assert not d.allowed, f"TERMS_HOSTILE must deny {op.value}: {d.reason}"


def test_legal_pending_permits_discover_and_prepare_but_denies_fetch():
    """LEGAL_PENDING = still under review. Cheap discovery/preparation
    is permitted (so the connector can enumerate + do local drafting)
    but any real fetch/submit is blocked until legal approves."""
    r = _legal_pending()
    d = allow(source_record=r, operation=Operation.DISCOVER)
    assert d.allowed, f"discover under pending must be allowed: {d.reason}"
    d = allow(source_record=r, operation=Operation.PREPARE)
    assert d.allowed
    d = allow(source_record=r, operation=Operation.FETCH)
    assert not d.allowed
    assert "legal_status_blocks_op" in d.reason


def test_legal_rejected_denies_every_op():
    r = _compliant()
    r["legalReviewStatus"] = LegalReviewStatus.REJECTED.value
    for op in Operation:
        d = allow(source_record=r, operation=op)
        assert not d.allowed
        # legal_block appears first for most; some ops (interact/submit)
        # hit license_block first because license is NOT_APPLICABLE.
        assert ("legal_status_blocks_op" in d.reason
                or "license_status_blocks_op" in d.reason
                or "license_status_not_in_permit_set" in d.reason)


# ------------------------------------------------------------------
# Kill switch
# ------------------------------------------------------------------
def test_kill_switch_overrides_everything(monkeypatch):
    monkeypatch.setenv("ADMIN_KILL_SWITCH_SOURCES", "greenhouse,lever")
    r = _compliant()
    r["licenseStatus"] = LicenseStatus.LICENSED.value  # would normally pass any op
    for op in Operation:
        d = allow(source_record=r, operation=op)
        assert not d.allowed, f"kill switch must deny {op.value}: {d.reason}"
        assert d.reason == "kill_switch_engaged"


def test_kill_switch_is_read_per_call_not_cached(monkeypatch):
    """Founder rail: 'no cache — the founder can revoke a source
    instantly by editing the env and hot-reloading.'"""
    r = _compliant()
    # Off
    monkeypatch.delenv("ADMIN_KILL_SWITCH_SOURCES", raising=False)
    d = allow(source_record=r, operation=Operation.DISCOVER)
    assert d.allowed
    # On — same call, no restart
    monkeypatch.setenv("ADMIN_KILL_SWITCH_SOURCES", "greenhouse")
    d = allow(source_record=r, operation=Operation.DISCOVER)
    assert not d.allowed
    # Off again
    monkeypatch.delenv("ADMIN_KILL_SWITCH_SOURCES", raising=False)
    d = allow(source_record=r, operation=Operation.DISCOVER)
    assert d.allowed


# ------------------------------------------------------------------
# raise_if_denied() helper
# ------------------------------------------------------------------
def test_raise_if_denied_raises_policy_denied():
    d = allow(source_record=_hostile_terms(), operation=Operation.FETCH)
    with pytest.raises(PolicyDenied):
        d.raise_if_denied()


def test_raise_if_denied_no_raise_on_allow():
    d = allow(source_record=_compliant(), operation=Operation.DISCOVER)
    # Must not raise
    d.raise_if_denied()


# ------------------------------------------------------------------
# NO LLM invariant — static grep
# ------------------------------------------------------------------
def test_source_policy_module_has_no_llm_calls():
    """FYND-ATLAS rail: 'no LLM in the policy path'. The module must
    not import any LLM SDK / emergent integration / anthropic / openai
    / gemini. Static grep locks the invariant."""
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "domains" / "source_policy" / "__init__.py"
    text = p.read_text(encoding="utf-8")
    forbidden = ("openai", "anthropic", "gemini",
                 "emergentintegrations", "generate_with_llm",
                 "llm_call", "chat.completions")
    hits = [f for f in forbidden if f in text.lower()]
    assert not hits, f"source_policy must NOT reference LLM SDKs: {hits}"

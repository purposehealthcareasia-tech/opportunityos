"""Phase 6d Batch D UI-gate WARN resolution · verbatim-consent scope rail.

The `/onboarding/launch` endpoint only accepts scopes in `LAUNCH_SCOPES`
(the closed set the React UI surfaces verbatim). Any other scope in
`req.consents` is rejected 400 `consent_scope_not_authorized_for_launch`,
so no consent row is ever written without a matching on-screen policy
text at authorize time.

These tests lock the rail. They deliberately do NOT call the full
composition — they only exercise the guard block that runs before any
DB writes.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from domains.onboarding.router import LAUNCH_SCOPES, LaunchRequest, launch
from domains.wave import WaveScope
from domains.preferences.models import PreferencesPayload


def _payload(consents: list[str]) -> LaunchRequest:
    return LaunchRequest(
        preferences=PreferencesPayload(),
        wave_scope=WaveScope(),
        consents=consents,
        policy_text_version="1.0",
    )


@pytest.mark.asyncio
async def test_launch_rejects_scope_not_in_launch_scopes():
    """Sending `discover_jobs` (valid SCOPE_KEY but not a LAUNCH_SCOPE)
    must fail 400 `consent_scope_not_authorized_for_launch` — no DB
    write, no partial launch."""
    req = _payload(list(LAUNCH_SCOPES) + ["discover_jobs"])
    fake_user = {"id": f"scope-rail-{uuid.uuid4().hex[:12]}", "email": "x@y.z"}
    with pytest.raises(HTTPException) as exc_info:
        await launch(req, user=fake_user)
    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert detail["error"] == "consent_scope_not_authorized_for_launch"
    assert "discover_jobs" in detail["extra"]
    assert set(detail["allowed"]) == set(LAUNCH_SCOPES)
    assert detail["step"] == "consent_scope_precheck"


@pytest.mark.asyncio
async def test_launch_rejects_multiple_extra_scopes():
    req = _payload(list(LAUNCH_SCOPES) + ["discover_jobs", "email_me", "generate_materials"])
    fake_user = {"id": f"scope-rail-{uuid.uuid4().hex[:12]}", "email": "x@y.z"}
    with pytest.raises(HTTPException) as exc_info:
        await launch(req, user=fake_user)
    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert detail["error"] == "consent_scope_not_authorized_for_launch"
    assert set(detail["extra"]) == {"discover_jobs", "email_me", "generate_materials"}


@pytest.mark.asyncio
async def test_launch_still_rejects_unknown_scope_before_launch_scope_rail():
    """An unknown scope name still fails on the earlier `unknown_consent_scopes`
    guard, not the LAUNCH_SCOPES rail — order of guards preserved."""
    req = _payload(list(LAUNCH_SCOPES) + ["not_a_real_scope_at_all"])
    fake_user = {"id": f"scope-rail-{uuid.uuid4().hex[:12]}", "email": "x@y.z"}
    with pytest.raises(HTTPException) as exc_info:
        await launch(req, user=fake_user)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "unknown_consent_scopes"


@pytest.mark.asyncio
async def test_launch_still_rejects_missing_required_before_launch_scope_rail():
    """Missing a required scope fails on the earlier
    `missing_required_consent_scopes` guard — order of guards preserved."""
    req = _payload(["submit_applications"])  # missing process_career_data
    fake_user = {"id": f"scope-rail-{uuid.uuid4().hex[:12]}", "email": "x@y.z"}
    with pytest.raises(HTTPException) as exc_info:
        await launch(req, user=fake_user)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "missing_required_consent_scopes"


@pytest.mark.asyncio
async def test_launch_scopes_constant_is_closed_set_of_two():
    """Byte-lock: LAUNCH_SCOPES is exactly the two scopes the UI shows.
    A future edit that expands LAUNCH_SCOPES without updating the React
    consent list breaks this test — forces coordinated FE/BE change."""
    assert LAUNCH_SCOPES == ("submit_applications", "process_career_data"), (
        "LAUNCH_SCOPES was expanded — update `frontend/src/pages/OnboardingLaunch.jsx` "
        "LAUNCH_SCOPES constant to match, then update this test."
    )

"""Phase 6d · Onboarding launch — approve-&-launch composition endpoint.

Combines the four post-upload user actions into ONE atomic request:
    1. `POST /claims/attest-all` — bulk-attest claim set (SHA-256 pinned)
    2. `POST /preferences` — save the confirmed spectrum
    3. `POST /consents` × N — one row per required scope (verbatim, NOT collapsed)
    4. `POST /wave/authorize` — kick the initial wave (standing_wave=true if opted in)

Atomicity: any step failing aborts the remaining steps and returns a
`partial_launch_blocked` error naming the failed step. This IS the
"single tap Authorize & Launch" — the UI never fires the four calls
separately; that would risk a half-launch state.

Consent rows are still WRITTEN VERBATIM per scope — the single tap is
UI/API composition, NOT consent collapsing. Each `consent_records` row
has its own `scope`, `policy_text_version`, `ts`. Revocation still
works per-scope from Settings.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import get_current_user
from core.policy import policy_version, SCOPE_KEYS
from domains.audit import service as audit
from domains.claims import service as claims_svc
from domains.consent import service as consent_svc
from domains.preferences import repository as pref_repo
from domains.preferences.models import PreferencesPayload
from domains.wave import WaveScope, authorize_wave

log = logging.getLogger("oppos.onboarding")
router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


# Scopes required to launch the auto-apply lane. Written verbatim, one
# row per scope. Adding a scope here is a policy-affecting change and
# must be reflected in `docs/PHASE-6-EVIDENCE.md`.
LAUNCH_SCOPES = ("submit_applications", "process_career_data")


class LaunchRequest(BaseModel):
    preferences: PreferencesPayload
    wave_scope: WaveScope
    consents: list[str] = Field(
        default_factory=lambda: list(LAUNCH_SCOPES),
        description="Scopes the user is granting in this single tap. "
                    "MUST be a subset of LAUNCH_SCOPES. Any missing "
                    "required scope aborts the launch — no partial.",
    )
    policy_text_version: Optional[str] = Field(
        default=None,
        description="Client-observed policy version at consent time. "
                    "If it doesn't match the current server policy version, "
                    "the launch is aborted (the user consented under a "
                    "different policy text — force a re-read).",
    )


@router.post("/launch", status_code=status.HTTP_201_CREATED)
async def launch(req: LaunchRequest, user: dict = Depends(get_current_user)):
    """Approve-&-launch — one atomic action combining bulk-attest,
    spectrum save, consent grants, and initial wave authorization.

    Rails:
      * Consent rows written verbatim per scope (NOT collapsed).
      * Any step failing aborts the remaining steps and returns 4xx
        with `partial_launch_blocked` + the specific failing step name.
      * `policy_text_version` MUST match the current server policy
        version — otherwise the client is out of date.
      * Every step's return value is included in the response so the
        UI can render "Attested 12 claims. 25 jobs queued. Standing
        Wave: ON" without a separate re-fetch.
    """
    # Policy version guard — user must consent to the current policy.
    current_policy = policy_version()
    if req.policy_text_version and req.policy_text_version != current_policy:
        raise HTTPException(
            status_code=409,
            detail={"error": "policy_version_stale",
                    "client_saw": req.policy_text_version,
                    "server_current": current_policy,
                    "step": "policy_version_check"},
        )

    # Required-scopes guard — cannot launch without ALL required scopes.
    missing = [s for s in LAUNCH_SCOPES if s not in req.consents]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"error": "missing_required_consent_scopes",
                    "missing": missing, "step": "consent_scope_precheck"},
        )
    # Unknown scopes guard — reject silently-accepted typos.
    unknown = [s for s in req.consents if s not in SCOPE_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_consent_scopes",
                    "unknown": unknown, "step": "consent_scope_precheck"},
        )
    # Non-LAUNCH scopes guard — verbatim-consent law: the UI must display
    # the exact text of every scope this endpoint will record. LAUNCH_SCOPES
    # is the closed set the UI surfaces on `/onboarding/launch`. Anything
    # else in `req.consents` (e.g., `discover_jobs`, `email_me`) belongs
    # on Settings, not the launch tap — rejecting here forces the caller
    # to grant/revoke those elsewhere so no consent row gets written
    # without matching on-screen policy text at authorize time.
    extra = [s for s in req.consents if s not in LAUNCH_SCOPES]
    if extra:
        raise HTTPException(
            status_code=400,
            detail={"error": "consent_scope_not_authorized_for_launch",
                    "extra": extra,
                    "allowed": list(LAUNCH_SCOPES),
                    "step": "consent_scope_precheck",
                    "message": "This endpoint only accepts the two launch "
                                "scopes surfaced verbatim on the /onboarding/launch "
                                "UI. Grant / revoke any other scope from Settings, "
                                "where its own policy text is displayed."},
        )

    # ---- STEP 1: bulk attest ----
    try:
        attest = await claims_svc.attest_all(
            user["id"], policy_text_version=current_policy,
            source="onboarding.launch",
        )
    except Exception as e:  # noqa: BLE001
        log.exception("onboarding.launch step=attest_all failed")
        raise HTTPException(status_code=500, detail={
            "error": "step_failed", "step": "attest_all",
            "reason": type(e).__name__}) from None

    # ---- STEP 2: save preferences (the confirmed spectrum) ----
    try:
        version = await pref_repo.next_version(user["id"])
        import uuid as _uuid
        from core.time_utils import utc_now as _now
        pref_doc = {
            "id": str(_uuid.uuid4()),
            "user_id": user["id"],
            "version": version,
            "payload": req.preferences.model_dump(),
            "updated_at": _now(),
        }
        await pref_repo.insert(pref_doc)
        prefs_result = {"version": version, "payload": pref_doc["payload"],
                        "updated_at": pref_doc["updated_at"]}
    except Exception as e:  # noqa: BLE001
        log.exception("onboarding.launch step=save_preferences failed")
        raise HTTPException(status_code=500, detail={
            "error": "step_failed", "step": "save_preferences",
            "reason": type(e).__name__}) from None

    # ---- STEP 3: consent grants, one row per scope, VERBATIM ----
    consent_row_ids: list[str] = []
    try:
        for scope in req.consents:
            row_id = await consent_svc.record(
                user_id=user["id"], scope=scope, granted=True,
                policy_text_version=current_policy,
                actor=user["id"], source="onboarding.launch",
            )
            consent_row_ids.append(row_id)
    except Exception as e:  # noqa: BLE001
        log.exception("onboarding.launch step=consent_grants failed")
        raise HTTPException(status_code=500, detail={
            "error": "step_failed", "step": "consent_grants",
            "reason": type(e).__name__,
            "consent_rows_written_before_failure": consent_row_ids,
        }) from None

    # ---- STEP 4: authorize the initial wave ----
    try:
        wave_result = await authorize_wave(req.wave_scope, user)
    except HTTPException:
        # authorize_wave raises HTTPException for known conditions
        # (missing consent, etc). Bubble the specific status.
        log.warning("onboarding.launch step=authorize_wave HTTPException — bubbling")
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("onboarding.launch step=authorize_wave failed")
        raise HTTPException(status_code=500, detail={
            "error": "step_failed", "step": "authorize_wave",
            "reason": type(e).__name__}) from None

    # Composite audit row — one atomic launch, one audit summary.
    await audit.write(user["id"], "onboarding.launch",
                       f"user:{user['id']}", {
                           "attested_count": attest.get("attested_count"),
                           "claim_set_hash": attest.get("claim_set_hash"),
                           "preferences_version": prefs_result["version"],
                           "consent_row_ids": consent_row_ids,
                           "wave_id": (wave_result or {}).get("wave_id"),
                           "wave_queued": (wave_result or {}).get("queued"),
                           "standing_wave": bool(req.wave_scope.standing_wave),
                       })

    return {
        "ok": True,
        "attest": attest,
        "preferences": prefs_result,
        "consent_row_ids": consent_row_ids,
        "wave": wave_result,
        "policy_text_version": current_policy,
    }

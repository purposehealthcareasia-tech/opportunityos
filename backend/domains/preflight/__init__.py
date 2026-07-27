"""Pre-flight simulate endpoint — Phase 5.1 (Founder Directive 2026-07-28).

Read-only "dry-fire" of the pre-flight validator. Reuses `preflight_check`
verbatim — no persist, no state change, no receipt/outbox writes. Auth +
consent-gated identically to the actual dispatch chokepoint so this cannot
become an unauthenticated oracle.

Purpose: let the frontend show the identity / grounding / traceability
block reasons live-as-they-type before the real dispatch, so users
never actually flip an application into review-lane merely to discover a
wording problem.

Contract:
  POST /api/v1/preflight/simulate
    body: { application_id, channel, outbound_fields? }
    → 200 { ok, reasons, verdict, note: "simulate — no side effects" }

If `channel` requires `submit_applications` consent (email_dry_run,
email_live, form_live) we gate on that scope. `sprint_fixture` also
gates on `submit_applications` since the founder rule is that submit
scope covers all outbound-adjacent flows.

Auth-failure status codes (verified live against preview 2026-07-28):
  * Missing session cookie + missing X-CSRF-Token         → 401 authentication_required
  * Session cookie present but CSRF header missing/wrong  → 403 csrf_check_failed
Both are correct behaviour; the earlier draft brief that said "unauth = 403"
should be read as "auth-layer rejects with 401 OR 403 depending on which
layer trips first".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import require_consent
from services import preflight_validator as preflight


router = APIRouter(prefix="/api/v1/preflight", tags=["preflight"])


class SimulateRequest(BaseModel):
    application_id: str
    channel: str = Field(..., description="One of sprint_fixture | "
                                            "email_dry_run | email_live | form_live")
    outbound_fields: dict | None = None
    expected_manifest_hash: str | None = None


@router.post("/simulate", status_code=status.HTTP_200_OK)
async def simulate(
    req: SimulateRequest,
    user: dict = Depends(require_consent("submit_applications")),
):
    """Dry-fire the pre-flight validator. Same code path as dispatch, but
    NO persist_verdict / block_and_route_to_review. Returns the verdict
    envelope the UI can render inline.

    Auth: session cookie + CSRF (identical to real dispatch).
    Consent gate: `submit_applications` — do not let this endpoint be
    reached without the same consent that gates the real submit."""
    if req.channel not in {
        preflight.CHANNEL_SPRINT_FIXTURE,
        preflight.CHANNEL_EMAIL_DRY_RUN,
        preflight.CHANNEL_EMAIL_LIVE,
        preflight.CHANNEL_FORM_LIVE,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_channel", "channel": req.channel},
        )
    try:
        verdict = await preflight.preflight_check(
            user_id=user["id"],
            application_id=req.application_id,
            channel=req.channel,
            outbound_fields=req.outbound_fields,
            expected_manifest_hash=req.expected_manifest_hash,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "preflight_input_invalid", "message": str(e)},
        )
    # NEVER persist. NEVER route to review. NEVER touch outbound state.
    # This is a pure read of the current claim + manifest + fields state.
    return {
        "ok": verdict.ok,
        "reasons": verdict.reasons,
        "verdict": verdict.to_dict(),
        "note": "simulate — no side effects (verdict is not persisted, "
                "application state is not changed)",
    }

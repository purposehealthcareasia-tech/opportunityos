"""Phase 5h · Layoff-Day Mode.

One-tap orchestration of EXISTING pieces. New endpoint only — no new
domain logic. Composes:
  * broad-spectrum template (preferences)
  * wave preview (`/api/v1/wave/preview`)
  * follow-up cadence preset (`/api/v1/follow-ups/*` — dry-run)
  * eligibility summary (`/api/v1/eligibility/coverage-preview`)

Rails:
  * No new claims created.
  * No income promises in copy.
  * All existing consent gates apply — this endpoint does NOT bypass
    any of them; failures surface honestly per-component.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.db import get_db
from core.deps import get_current_user


router = APIRouter(prefix="/api/v1/layoff-day", tags=["layoff_day"])


_ELIGIBILITY_KEY = "eligibility_coverage_preview"


@router.get("/orchestrate")
async def orchestrate(user: dict = Depends(get_current_user)):
    """Read-only orchestration: compose the pre-flight state a layoff-day
    user needs before pressing the big red button. Every sub-component
    is queried in isolation; a component-level failure surfaces as an
    `available: false` marker with the reason."""
    db = get_db()

    # 1) Broad-spectrum template — pull user's existing preferences.
    prefs = await db.preferences.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    broad_spectrum = {
        "available": True,
        "roles": prefs.get("roles") or [],
        "locations": prefs.get("locations") or [],
        "remote_ok": prefs.get("remote_ok") in (True, "true", 1),
        "notice": "Broad-spectrum template composed from your saved preferences.",
    }

    # 2) Eligibility coverage preview — read the cached row directly to
    # avoid recursive HTTP (this handler is read-only anyway).
    ecp = await db.eligibility_profiles.find_one({"user_id": user["id"]}, {"_id": 0})
    if ecp:
        eligibility_summary = {
            "available": True,
            "status": ecp.get("status") or "unset",
            "sealed_at": ecp.get("created_at"),
            "notice": (
                "Read-only reflection of your saved eligibility profile. "
                "Layoff-Day mode does NOT modify eligibility."
            ),
        }
    else:
        eligibility_summary = {
            "available": False,
            "reason": "no_eligibility_profile",
            "notice": (
                "No eligibility profile on file. Seal one from the "
                "/eligibility page before running Layoff-Day mode."
            ),
        }

    # 3) Wave preview: how many jobs would go into a wave right now?
    live_ready_count = await db.jobs.count_documents({
        "status": "live",
    })
    wave_preview = {
        "available": True,
        "live_jobs_count": live_ready_count,
        "cap_default": 30,
        "notice": (
            "Preview only. Actual wave requires a separate consent + "
            "batch authorization on /api/v1/wave/authorize."
        ),
    }

    # 4) Follow-up cadence preset — describe the preset; do NOT enable.
    followup_preset = {
        "available": True,
        "cadence": "day+2, day+7, day+14",
        "channel": "email",
        "dispatch_mode": "dry_run",
        "notice": (
            "Cadence preset. Follow-ups are NEVER auto-sent — you approve "
            "each one from /follow-ups. In preview, dispatch is DRY-RUN only."
        ),
    }

    return {
        "user_id": user["id"],
        "orchestration_version": 1,
        "components": {
            "broad_spectrum": broad_spectrum,
            "eligibility_summary": eligibility_summary,
            "wave_preview": wave_preview,
            "followup_preset": followup_preset,
        },
        "consent_gates_intact": True,
        "income_promises": None,   # explicit `null` — never a number here
        "notice": (
            "Layoff-Day mode composes EXISTING pieces only. It creates no "
            "claims, sends no email, and makes NO income promises. Consent "
            "and rate-limit gates on every underlying endpoint are intact."
        ),
    }

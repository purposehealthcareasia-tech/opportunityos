"""Phase 6f · Form-route telemetry service + admin surface + user-side
autopilot-gate readout.

* `POST /api/v1/form-telemetry` — sprint client sends per-fill sample
  after each 1-keypress sprint. One row per application session.
* `GET  /api/v1/autopilot/status` — user's current autopilot gate state:
  allowed / locked + reason + measurable metrics.
* `GET  /api/v1/admin/telemetry/form-accuracy` — admin/owner-only global
  aggregate over the last 30 days + per-user rows (for the accuracy
  dashboard).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import get_current_user
from core.db import get_db
from domains.audit import service as audit
from services import autopilot_gate

router = APIRouter(prefix="/api/v1", tags=["form_telemetry"])


class TelemetrySample(BaseModel):
    application_id: str = Field(min_length=1, max_length=200)
    field_count: int = Field(ge=0, le=500)
    field_matches: int = Field(ge=0, le=500)
    mismatches: list[dict] = Field(default_factory=list, max_length=100)
    session_ms: int | None = Field(default=None, ge=0, le=3_600_000)


@router.post("/form-telemetry", status_code=status.HTTP_201_CREATED)
async def record_sample(req: TelemetrySample,
                         user: dict = Depends(get_current_user)):
    """Insert ONE telemetry row from a sprint session. `field_matches`
    must be <= `field_count` (validated). We DO NOT store the actual
    field values here — only counts + a short mismatches summary.
    That keeps the per-fill telemetry surface privacy-honest."""
    if req.field_matches > req.field_count:
        raise HTTPException(status_code=400, detail={
            "error": "matches_exceed_field_count",
            "field_count": req.field_count,
            "field_matches": req.field_matches,
        })
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": req.application_id,
        "field_count": req.field_count,
        "field_matches": req.field_matches,
        "mismatches": req.mismatches[:100],  # cap
        "session_ms": req.session_ms,
        "sample_ts": datetime.now(timezone.utc),
    }
    await get_db().form_fill_telemetry.insert_one(row)
    return {"ok": True, "id": row["id"]}


@router.get("/autopilot/status")
async def autopilot_status(user: dict = Depends(get_current_user)):
    """Return the caller's autopilot auto-submit gate state.

    Rails: ships DISABLED by default (`user_not_opted_in`). Even with
    opt-in, unlock requires n_fields >= MIN_SAMPLE_SIZE AND
    Wilson-95%-CI lower bound of accuracy >= MIN_ACCURACY (see
    `services/autopilot_gate.py` for the locked constants).
    """
    allowed, reason, metrics = await autopilot_gate.is_auto_submit_allowed(user["id"])
    return {
        "allowed": allowed,
        "reason": reason,
        "metrics": metrics,
        "gate_constants": {
            "MIN_ACCURACY": autopilot_gate.MIN_ACCURACY,
            "MIN_SAMPLE_SIZE": autopilot_gate.MIN_SAMPLE_SIZE,
        },
        "shipping_default": "disabled",
        "honest_copy": ("Autopilot auto-submit ships disabled by default. "
                         "Even after opt-in it stays locked until you've "
                         f"filled at least {autopilot_gate.MIN_SAMPLE_SIZE} "
                         "form-fields via the sprint route AND the "
                         "Wilson-95%-CI lower bound of your fill accuracy "
                         f"clears {autopilot_gate.MIN_ACCURACY*100:.0f}%."),
    }


class OptInRequest(BaseModel):
    opt_in: bool


@router.post("/autopilot/opt-in", status_code=status.HTTP_201_CREATED)
async def autopilot_opt_in(req: OptInRequest,
                             user: dict = Depends(get_current_user)):
    """Per-user opt-in toggle. Persists to `user_settings`. Note the
    gate STILL enforces the accuracy threshold — opting in alone does
    NOT unlock auto-submit."""
    db = get_db()
    now = datetime.now(timezone.utc)
    await db.user_settings.update_one(
        {"user_id": user["id"]},
        {"$set": {"autopilot_auto_submit_opt_in": bool(req.opt_in),
                   "updated_at": now}},
        upsert=True,
    )
    await audit.write(user["id"], "autopilot.opt_in",
                       f"user:{user['id']}",
                       {"opt_in": bool(req.opt_in)})
    return {"ok": True, "opt_in": bool(req.opt_in)}


# ---------------------------------------------------------------------------
# Admin — global accuracy readout (30-day rolling)
# ---------------------------------------------------------------------------
def _is_admin_or_owner(user: dict) -> bool:
    if not user:
        return False
    if user.get("role") in ("admin", "support"):
        return True
    email = (user.get("email") or "").lower()
    csv = os.environ.get("PRIVATE_AUTOPILOT_OWNER_EMAILS", "")
    owners = {e.strip().lower() for e in csv.split(",") if e.strip()}
    return email in owners


@router.get("/admin/telemetry/form-accuracy")
async def admin_form_accuracy(user: dict = Depends(get_current_user)):
    """Owner/admin-only rolling-30d aggregate + per-user metrics."""
    if not _is_admin_or_owner(user):
        raise HTTPException(status_code=403, detail={"error": "admin_or_owner_required"})
    db = get_db()
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    total_fields = 0
    total_matches = 0
    per_user_matches: dict[str, tuple[int, int]] = {}
    async for r in db.form_fill_telemetry.find(
        {"sample_ts": {"$gte": cutoff}},
        {"_id": 0, "user_id": 1, "field_count": 1, "field_matches": 1},
    ):
        uid = r["user_id"]
        fc = int(r.get("field_count") or 0)
        fm = min(int(r.get("field_matches") or 0), fc)
        if fc <= 0:
            continue
        total_fields += fc
        total_matches += fm
        m, f = per_user_matches.get(uid, (0, 0))
        per_user_matches[uid] = (m + fm, f + fc)
    global_acc = (total_matches / total_fields) if total_fields > 0 else 0.0
    global_ci_low = autopilot_gate.wilson_lower_bound(total_matches, total_fields) if total_fields > 0 else 0.0
    per_user_rows = []
    for uid, (m, f) in per_user_matches.items():
        acc = m / f if f > 0 else 0.0
        ci_low = autopilot_gate.wilson_lower_bound(m, f) if f > 0 else 0.0
        per_user_rows.append({
            "user_id": uid, "n_fields": f, "matches": m,
            "accuracy_pct": round(acc * 100, 3),
            "ci95_lower_pct": round(ci_low * 100, 3),
        })
    per_user_rows.sort(key=lambda r: r["n_fields"], reverse=True)
    return {
        "window_days": 30,
        "global": {
            "n_fields": total_fields, "matches": total_matches,
            "accuracy_pct": round(global_acc * 100, 3),
            "ci95_lower_pct": round(global_ci_low * 100, 3),
        },
        "per_user": per_user_rows,
        "gate_constants": {
            "MIN_ACCURACY": autopilot_gate.MIN_ACCURACY,
            "MIN_SAMPLE_SIZE": autopilot_gate.MIN_SAMPLE_SIZE,
        },
    }

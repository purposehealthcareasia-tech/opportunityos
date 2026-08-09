"""Phase 5b · Material A/B Testing.

Two material variants per spectrum. Outcomes ledger (`application_outcomes`)
attributes responses per variant via `material_ab_assignments`. Descriptive
stats only — honest small-n labeling; no significance claims under n=30.

Rails:
  * User attaches a variant label (`A` or `B`) to a specific
    `ai_generations` row for an application before sending.
  * We never *assign* a variant automatically — the user picks. That
    keeps the semantics honest: any bias in variant selection is
    user-owned, not model-owned.
  * Response attribution: join `application_outcomes` where
    `event in ("interview_scheduled", "response_received", "offer",
    "rejected_with_reason")` on `application_id` → variant.
  * Report NEVER shows p-values or "winner" — descriptive-only rails.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import get_current_user


router = APIRouter(prefix="/api/v1/materials/ab", tags=["materials_ab"])


_VARIANTS = ("A", "B")
_SMALL_N_THRESHOLD = 30  # any variant with n<30 → descriptive only

# Response event names that count as "responded" (positive OR negative).
# We include `rejected_with_reason` because a rejection is still a
# response signal (not a ghost). `ghosted` / `no_response` never count.
_RESPONSE_EVENTS = (
    "interview_scheduled",
    "response_received",
    "offer",
    "rejected_with_reason",
)


class AttachRequest(BaseModel):
    application_id: str = Field(..., min_length=8, max_length=64)
    generation_id: str = Field(..., min_length=8, max_length=64)
    variant_label: Literal["A", "B"]
    spectrum_key: Optional[str] = Field(
        None, max_length=80,
        description="Optional grouping key so multiple A/B tests can run in parallel (e.g. 'senior-swe-remote'). Report groups by this.",
    )


@router.post("/attach")
async def attach_variant(req: AttachRequest, user: dict = Depends(get_current_user)):
    """Attach an A/B variant label to a generation. Idempotent on
    (user_id, application_id, generation_id) — a re-attach flips the
    label if the user changed their mind, preserving one row."""
    db = get_db()
    # Verify the application belongs to the user (owner rail).
    app_row = await db.applications.find_one(
        {"id": req.application_id, "user_id": user["id"]}
    )
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")

    now_iso = datetime.now(timezone.utc).isoformat()
    existing = await db.material_ab_assignments.find_one({
        "user_id": user["id"],
        "application_id": req.application_id,
        "generation_id": req.generation_id,
    })
    if existing:
        await db.material_ab_assignments.update_one(
            {"id": existing["id"]},
            {"$set": {"variant_label": req.variant_label,
                      "spectrum_key": req.spectrum_key or existing.get("spectrum_key") or "",
                      "updated_at": now_iso}},
        )
        return {"attached": True, "id": existing["id"], "updated": True,
                "variant_label": req.variant_label}

    aid = str(uuid.uuid4())
    await db.material_ab_assignments.insert_one({
        "id": aid,
        "user_id": user["id"],
        "application_id": req.application_id,
        "generation_id": req.generation_id,
        "variant_label": req.variant_label,
        "spectrum_key": req.spectrum_key or "",
        "created_at": now_iso,
        "updated_at": now_iso,
    })
    return {"attached": True, "id": aid, "updated": False,
            "variant_label": req.variant_label}


@router.get("/report")
async def report(
    spectrum_key: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Descriptive report grouped by variant. Small-n gated: any variant
    with n<30 → `small_n: true` + explicit "no significance claim" note.
    """
    db = get_db()
    q = {"user_id": user["id"]}
    if spectrum_key:
        q["spectrum_key"] = spectrum_key

    assignments = [a async for a in db.material_ab_assignments.find(q)]
    if not assignments:
        return {
            "variants": {v: _empty_variant() for v in _VARIANTS},
            "small_n": True,
            "cohort_notice": "No A/B assignments yet — nothing to describe.",
            "total_assignments": 0,
        }

    # Group by variant.
    by_variant: dict[str, list[dict]] = {v: [] for v in _VARIANTS}
    for a in assignments:
        v = a.get("variant_label")
        if v in by_variant:
            by_variant[v].append(a)

    app_ids_by_variant = {
        v: [a["application_id"] for a in rows] for v, rows in by_variant.items()
    }
    variant_stats: dict[str, dict] = {}
    small_n_any = False
    for v, app_ids in app_ids_by_variant.items():
        if not app_ids:
            variant_stats[v] = _empty_variant()
            small_n_any = True
            continue
        # Response count for this variant.
        n = len(app_ids)
        outcomes = db.application_outcomes.find({
            "application_id": {"$in": app_ids},
            "event": {"$in": list(_RESPONSE_EVENTS)},
        })
        responded_apps: set[str] = set()
        days_lags: list[float] = []
        async for o in outcomes:
            responded_apps.add(o["application_id"])
            lag = o.get("lag_days")
            if isinstance(lag, (int, float)) and lag >= 0:
                days_lags.append(float(lag))
        responded = len(responded_apps)
        response_rate = round(responded / n, 4) if n else 0.0
        median_lag = _median(days_lags) if days_lags else None
        if n < _SMALL_N_THRESHOLD:
            small_n_any = True
        variant_stats[v] = {
            "n": n,
            "responded": responded,
            "response_rate": response_rate,
            "median_days_to_response": median_lag,
        }

    return {
        "variants": variant_stats,
        "small_n": small_n_any,
        "cohort_notice": _cohort_notice(small_n_any),
        "total_assignments": sum(v["n"] for v in variant_stats.values()),
    }


def _empty_variant() -> dict:
    return {"n": 0, "responded": 0, "response_rate": 0.0, "median_days_to_response": None}


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return round(s[n // 2], 3)
    return round((s[n // 2 - 1] + s[n // 2]) / 2, 3)


def _cohort_notice(small_n: bool) -> str:
    if small_n:
        return (
            f"Small-n cohort (any variant with n<{_SMALL_N_THRESHOLD}). Descriptive "
            "counts only — no significance claim is meaningful at this size. "
            "Consider running more applications per variant before drawing conclusions."
        )
    return (
        "Descriptive counts and response rates only. Fynd never claims "
        "statistical significance — descriptive comparison is the honest reading."
    )

"""Analytics — Phase 5 S17 personal funnel + QI counter + minutes_to_prepare.

Honesty rules:
  - REAL rows only for the personal-funnel totals; SAMPLE-job applications are
    counted in a separate bucket and clearly labelled by the UI.
  - No cohort/global stats — no cohort exists yet.
  - Honest empty state when there is no data: totals=0 + sample_note explains "no
    applications yet — nothing to chart".
  - minutes_to_prepare distribution is omitted (returned as null) when there are
    zero data points; never fabricated.
"""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends
from core.db import get_db
from core.deps import get_current_user


router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def _is_sample(app_row: dict) -> bool:
    return bool((app_row.get("job_snapshot") or {}).get("is_sample"))


def _totals_bucket(apps: list[dict], outcomes_by_app: dict[str, list[dict]]) -> dict[str, int]:
    prepared = submitted = response = interview = offer = closed = 0
    for a in apps:
        # Prepared = ever reached preparing or beyond
        st = a["state"]
        if st in {"preparing", "awaiting_approval", "approved", "submitting",
                  "submitted", "response", "interview", "offer", "closed"}:
            prepared += 1
        if st in {"submitting", "submitted", "response", "interview", "offer", "closed"}:
            submitted += 1
        if st in {"response", "interview", "offer"}:
            response += 1
        if st in {"interview", "offer"}:
            interview += 1
        if st == "offer":
            offer += 1
        if st == "closed":
            closed += 1
    return {"prepared": prepared, "submitted": submitted, "response": response,
            "interview": interview, "offer": offer, "closed": closed}


def _minutes_between(a: dict, target_state: str) -> float | None:
    """If the application has both a created_at and a snapshot showing it reached
    target_state, return minutes elapsed. v0.1 uses the created_at → submitted_at
    delta because we don't track per-state timestamps yet."""
    if a.get("submitted_at") and a.get("created_at"):
        try:
            from datetime import datetime as _dt
            end = a["submitted_at"]
            start = a["created_at"]
            if isinstance(start, str):
                start = _dt.fromisoformat(start.replace("Z", "+00:00"))
            if isinstance(end, str):
                end = _dt.fromisoformat(end.replace("Z", "+00:00"))
            delta = (end - start).total_seconds() / 60.0
            return round(delta, 1) if delta >= 0 else None
        except Exception:
            return None
    return None


@router.get("/funnel")
async def read_funnel(user: dict = Depends(get_current_user)):
    db = get_db()
    apps = [a async for a in db.applications.find({"user_id": user["id"]}, {"_id": 0})]
    outcomes: list[dict] = []
    async for o in db.outcomes.find({"user_id": user["id"]}, {"_id": 0}):
        outcomes.append(o)
    outcomes_by_app: dict[str, list[dict]] = {}
    for o in outcomes:
        outcomes_by_app.setdefault(o["application_id"], []).append(o)

    real_apps = [a for a in apps if not _is_sample(a)]
    sample_apps = [a for a in apps if _is_sample(a)]

    totals = _totals_bucket(real_apps, outcomes_by_app)
    sample_totals = _totals_bucket(sample_apps, outcomes_by_app)

    # Conversion percentages (integer, floor). None when denominator is 0.
    def conv(num: int, den: int) -> int | None:
        return int(100 * num / den) if den > 0 else None

    conversion = {
        "prepared_to_submitted": conv(totals["submitted"], totals["prepared"]),
        "submitted_to_response": conv(totals["response"], totals["submitted"]),
        "response_to_interview": conv(totals["interview"], totals["response"]),
        "interview_to_offer":    conv(totals["offer"], totals["interview"]),
    }

    # QI counter — interviews.qualified=true (excluding SAMPLE applications).
    qi_total = await db.interviews.count_documents({
        "user_id": user["id"], "qualified": True,
    })

    # minutes_to_prepare distribution — REAL apps only.
    times = [t for t in (_minutes_between(a, "submitted") for a in real_apps) if t is not None]
    if times:
        times.sort()
        mid = len(times) // 2
        median = times[mid] if len(times) % 2 == 1 else round((times[mid - 1] + times[mid]) / 2, 1)
        minutes_to_prepare = {
            "count": len(times),
            "min": times[0],
            "median": median,
            "max": times[-1],
        }
    else:
        minutes_to_prepare = None

    empty = totals["prepared"] == 0 and len(sample_apps) == 0
    sample_note = ("SAMPLE — excluded from your metrics. These rows come from the "
                   "seeded demo employers used for the guided tour.") if sample_apps else \
                  ("No applications yet — start on the Feed and shortlist a role to see your funnel."
                   if empty else "")

    return {
        "totals": totals,
        "sample": sample_totals,
        "conversion": conversion,
        "qi_total": qi_total,
        "minutes_to_prepare": minutes_to_prepare,
        "sample_note": sample_note,
        "empty": empty,
    }

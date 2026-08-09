"""Phase 5g · Employer Dashboard (read-only v1).

Owner-scoped view for a CONNECTED employer: their OWN response-speed
rank + application quality stats. ZERO cross-employer disclosure.

Rails:
  * Employer identity is derived from the caller's authenticated
    employer_membership row (must exist and be verified).
  * Every stat is computed from `application_outcomes` where
    `employer_canonical_key == this_employer` and NEVER joins with
    other employers.
  * A "rank" is expressed ONLY as `percentile_bucket` (top 10%,
    top 25%, median, bottom half). The universe of employers used
    for the percentile calculation is the caller's OWN employers if
    they own multiple; else the response is descriptive-only with
    no rank.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.db import get_db
from core.deps import get_current_user


router = APIRouter(prefix="/api/v1/employer-dashboard", tags=["employer_dashboard"])


async def _resolve_employer(user_id: str) -> str:
    """Return the caller's canonical employer key. Raises 403 if the
    caller has no verified employer membership."""
    db = get_db()
    m = await db.employer_memberships.find_one(
        {"user_id": user_id, "verified": True},
    )
    if not m:
        raise HTTPException(status_code=403, detail={
            "error": "employer_membership_required",
            "message": "Employer dashboard requires a verified employer_memberships row for this account."
        })
    return m["employer_canonical_key"]


@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)):
    employer = await _resolve_employer(user["id"])
    db = get_db()
    # Pull our OWN outcome rows for this employer.
    total_apps = await db.applications.count_documents({
        "employer_canonical_key": employer,
    })
    responded_events = ("interview_scheduled", "response_received",
                        "offer", "rejected_with_reason")
    responded = await db.application_outcomes.count_documents({
        "employer_canonical_key": employer,
        "event": {"$in": list(responded_events)},
    })
    # Median lag (in days) from submission → first non-viewed outcome.
    lags = []
    async for o in db.application_outcomes.find({
        "employer_canonical_key": employer,
        "event": {"$in": list(responded_events)},
        "lag_days": {"$type": "number"},
    }, {"_id": 0, "lag_days": 1}):
        lags.append(o["lag_days"])
    lags.sort()
    if not lags:
        median = None
    elif len(lags) % 2 == 1:
        median = lags[len(lags) // 2]
    else:
        median = round((lags[len(lags) // 2 - 1] + lags[len(lags) // 2]) / 2, 2)

    # Application quality signal: fraction that passed all gates
    # (score ≥ 60) — user-scoped in the underlying feed but the
    # employer view surfaces the AGGREGATE only.
    quality = None
    if total_apps > 0:
        passing = await db.applications.count_documents({
            "employer_canonical_key": employer,
            "score": {"$gte": 60},
        })
        quality = round(passing / total_apps, 3)

    # Own-data-only rank: if this account owns ≥2 employers, we
    # compute a percentile bucket AMONG the caller's own employers.
    # Otherwise no rank is surfaced.
    memberships = [m async for m in db.employer_memberships.find(
        {"user_id": user["id"], "verified": True}
    )]
    rank_bucket = None
    if len(memberships) >= 2:
        own_medians = []
        for mem in memberships:
            emp = mem["employer_canonical_key"]
            emp_lags = []
            async for o in db.application_outcomes.find({
                "employer_canonical_key": emp,
                "event": {"$in": list(responded_events)},
                "lag_days": {"$type": "number"},
            }, {"_id": 0, "lag_days": 1}):
                emp_lags.append(o["lag_days"])
            if emp_lags:
                emp_lags.sort()
                emed = (
                    emp_lags[len(emp_lags) // 2]
                    if len(emp_lags) % 2 == 1
                    else (emp_lags[len(emp_lags) // 2 - 1] + emp_lags[len(emp_lags) // 2]) / 2
                )
                own_medians.append((emp, emed))
        if median is not None and own_medians:
            faster_than = sum(1 for _e, m in own_medians if m > median)
            pct = round(faster_than / len(own_medians), 3)
            if pct >= 0.9:
                rank_bucket = "top_10pct"
            elif pct >= 0.75:
                rank_bucket = "top_25pct"
            elif pct >= 0.5:
                rank_bucket = "above_median"
            else:
                rank_bucket = "below_median"

    return {
        "employer_canonical_key": employer,
        "total_applications": total_apps,
        "responded_count": responded,
        "response_rate": round(responded / total_apps, 3) if total_apps else None,
        "median_days_to_response": median,
        "application_quality_pass_rate": quality,
        "rank_bucket": rank_bucket,
        "rank_scope": (
            "own_employers_only" if rank_bucket else "not_available"
        ),
        "cross_employer_disclosure": False,
        "notice": (
            "Own-data only. Cross-employer disclosure is a hard rail. "
            "The percentile bucket, when present, is computed exclusively "
            "over YOUR OWN connected employers."
        ),
    }

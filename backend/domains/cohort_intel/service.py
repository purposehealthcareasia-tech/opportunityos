"""Phase 5j · Cohort Intelligence.

Anonymized pipeline. Same hard rule as /standards: HONEST EMPTY STATE.
ZERO synthetic cohort numbers — if the population is too small to be
useful, we say so and return no data.

Rails:
  * `_MIN_COHORT_SIZE = 50` — below this, every stat is null and the
    empty-state notice is surfaced.
  * User-scoped anonymization: all cohort inputs are aggregated by
    coarse eligibility class only — never by individual user data.
  * NO synthetic numbers, EVER. If the input pool is thin, the
    response is transparently empty.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.db import get_db
from core.deps import get_current_user


router = APIRouter(prefix="/api/v1/cohort-intel", tags=["cohort_intel"])


_MIN_COHORT_SIZE = 50


@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)):
    """Coarse-grained cohort summary. If the pool is < _MIN_COHORT_SIZE
    we return `data_available: false` + a transparent notice. We NEVER
    fill in synthetic numbers."""
    db = get_db()
    total_users = await db.users.count_documents({})
    total_apps = await db.applications.count_documents({})

    if total_users < _MIN_COHORT_SIZE:
        return {
            "data_available": False,
            "current_pool_size": total_users,
            "min_pool_size": _MIN_COHORT_SIZE,
            "buckets": [],
            "notice": (
                f"Cohort intelligence needs at least {_MIN_COHORT_SIZE} "
                f"users to unlock — no data yet ({total_users} on file). "
                "We refuse to invent numbers to fill this space. Come "
                "back when the pool has grown."
            ),
        }

    # Real aggregation, only reached when pool is large enough.
    buckets: list[dict] = []
    async for row in db.eligibility_profiles.aggregate([
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gte": _MIN_COHORT_SIZE // 5}}},  # min per-bucket 10
    ]):
        buckets.append({
            "eligibility_class": row["_id"] or "unset",
            "n": row["n"],
        })
    return {
        "data_available": True,
        "current_pool_size": total_users,
        "total_applications": total_apps,
        "buckets": buckets,
        "notice": (
            "Coarse anonymized aggregates only. Individual user data "
            "is never disclosed. Buckets with < 10 members are also "
            "omitted for k-anonymity."
        ),
    }

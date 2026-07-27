"""Supply-Reality Dashboard (Phase 3 Founder Brief).

One endpoint that answers: "What's really available right now, and how much of
my daily budget have I burned?"

  * live_jobs               — total live jobs in the feed (all lanes)
  * live_by_lane            — {career, income_now}
  * new_today               — first_seen within last 24h
  * within_25mi_of_phoenix  — proximity radius stat
  * backlog                 — my applications in non-terminal states
  * submitted_today         — my receipts count today
  * daily_submit_cap        — plan cap (subscriptions)
  * budget_remaining_today  — cap - submitted_today
  * employer_cap            — {cap, window_days}
  * top_employers_last_30d  — [{employer, count}] for user's own applications

Consent-gated on `discover_jobs`. Returns only the requesting user's data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from core.deps import require_consent
from core.db import get_db
from services import employer_cap as cap_svc
from domains.subscriptions import service as subs_svc


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


async def _new_today(db) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return await db.jobs.count_documents({"status": "live", "first_seen": {"$gte": since}})


async def _within_radius(db, mi: int) -> int:
    return await db.jobs.count_documents({"status": "live",
                                            "distance_from_phoenix_mi": {"$lte": mi}})


async def _receipts_today(db, user_id: str) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return await db.submission_receipts.count_documents({"user_id": user_id,
                                                          "created_at": {"$gte": start}})


async def _top_employers_last_30d(db, user_id: str) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    pipe = [
        {"$match": {"user_id": user_id, "created_at": {"$gte": since}}},
        {"$group": {"_id": "$job_snapshot.company_name", "n": {"$sum": 1}}},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"n": -1}},
        {"$limit": 10},
    ]
    return [{"employer": r["_id"], "count": r["n"]}
            async for r in db.applications.aggregate(pipe)]


@router.get("/supply-reality")
async def supply_reality(user: dict = Depends(require_consent("discover_jobs"))):
    db = get_db()
    live_all = await db.jobs.count_documents({"status": "live"})
    live_career = await db.jobs.count_documents({"status": "live", "lane": "career"})
    live_income = await db.jobs.count_documents({"status": "live", "lane": "income_now"})
    new_today = await _new_today(db)
    within_25 = await _within_radius(db, 25)
    within_60 = await _within_radius(db, 60)

    backlog = await db.applications.count_documents({
        "user_id": user["id"],
        "state": {"$in": ["shortlisted", "preparing", "awaiting_approval",
                            "approved", "submitting", "submitted", "response",
                            "interview", "offer"]},
    })
    submitted_today = await _receipts_today(db, user["id"])
    plan = await subs_svc.get_plan_config(user["id"])
    top_employers = await _top_employers_last_30d(db, user["id"])

    return {
        "supply": {
            "live_jobs": live_all,
            "live_by_lane": {"career": live_career, "income_now": live_income},
            "new_today": new_today,
            "within_25mi_of_phoenix": within_25,
            "within_60mi_of_phoenix": within_60,
        },
        "budget": {
            "plan": plan.slug,
            "plan_label": plan.label,
            "daily_submit_cap": plan.daily_submit_cap,
            "submitted_today": submitted_today,
            "budget_remaining_today": max(0, plan.daily_submit_cap - submitted_today),
        },
        "employer_cap": {
            "cap": cap_svc.EMPLOYER_CAP_PER_30D,
            "window_days": cap_svc.CAP_WINDOW_DAYS,
            "top_employers_last_30d": top_employers,
        },
        "backlog": {
            "open_applications": backlog,
        },
    }

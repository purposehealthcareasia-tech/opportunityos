"""Cap enforcement helpers used across the app — hourly jobs_processed, monthly
apps_prepared. Daily submits already live in applications/service.py.

Caps come from PLAN_CATALOG (see backend/domains/billing/service.py):
  free  25/hr  5/mo    3/day
  plus  100    60      15
  pro   250    200     25
  max   500    400*    40   (* soft — warn, don't block)
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from core.db import get_db
from domains.subscriptions import service as subs_svc


CAPS = {
    "free": {"jobs_hourly": 25,  "prepared_monthly": 5,   "submits_daily": 3},
    "plus": {"jobs_hourly": 100, "prepared_monthly": 60,  "submits_daily": 15},
    "pro":  {"jobs_hourly": 250, "prepared_monthly": 200, "submits_daily": 25},
    "max":  {"jobs_hourly": 500, "prepared_monthly": 400, "submits_daily": 40},
}
SOFT_CAP_PLANS = {"max"}


def _hour_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=1)


def _month_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        end = start.replace(year=now.year + 1, month=1)
    else:
        end = start.replace(month=now.month + 1)
    return start, end


async def _plan_slug(user_id: str) -> str:
    sub = await subs_svc._ensure_subscription(user_id)  # noqa: SLF001
    return sub.get("plan") or "free"


async def check_jobs_hourly(user_id: str) -> tuple[int, int, str]:
    """Return (used_this_hour, cap, plan). Raises 429 if exceeded (hard).
    'jobs_processed' = discovered+verified+scored for this user, counted from match_scores.created_at
    (each row is a scoring event)."""
    plan = await _plan_slug(user_id)
    cap = CAPS[plan]["jobs_hourly"]
    start, end = _hour_window()
    used = await get_db().match_scores.count_documents({
        "user_id": user_id, "created_at": {"$gte": start, "$lt": end},
    })
    if used >= cap:
        raise HTTPException(status_code=429, detail={
            "error": "cap_exceeded", "meter": "jobs_processed", "plan": plan,
            "cap": cap, "used": used, "resets_at": end.isoformat(),
            "message": f"Hourly jobs_processed cap ({cap}/hr on {plan}) hit. Resets at {end.isoformat()}.",
        })
    return used, cap, plan


async def check_prepared_monthly(user_id: str) -> tuple[int, int, str, bool]:
    """Return (used_this_month, cap, plan, is_soft). Raises 429 if HARD exceeded.

    For MAX plan the 400 cap is SOFT — no raise, just a warning surfaced.
    """
    plan = await _plan_slug(user_id)
    cap = CAPS[plan]["prepared_monthly"]
    start, end = _month_window()
    used = await get_db().ai_generations.count_documents({
        "user_id": user_id, "task": "tailor_resume_lines", "created_at": {"$gte": start, "$lt": end},
    })
    is_soft = plan in SOFT_CAP_PLANS
    if used >= cap:
        if is_soft:
            return used, cap, plan, True
        raise HTTPException(status_code=429, detail={
            "error": "cap_exceeded", "meter": "applications_prepared", "plan": plan,
            "cap": cap, "used": used, "resets_at": end.isoformat(),
            "message": f"Monthly prepared cap ({cap}/mo on {plan}) hit. Resets at {end.isoformat()}.",
        })
    return used, cap, plan, is_soft


async def usage_snapshot(user_id: str) -> dict:
    """Aggregate current meter state for the /billing UI."""
    plan = await _plan_slug(user_id)
    hour_start, hour_end = _hour_window()
    month_start, month_end = _month_window()
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    db = get_db()
    jobs_this_hour = await db.match_scores.count_documents({
        "user_id": user_id, "created_at": {"$gte": hour_start, "$lt": hour_end},
    })
    prepared_this_month = await db.ai_generations.count_documents({
        "user_id": user_id, "task": "tailor_resume_lines", "created_at": {"$gte": month_start, "$lt": month_end},
    })
    submitted_today = await db.submission_receipts.count_documents({
        "user_id": user_id, "ts": {"$gte": day_start, "$lt": day_end},
    })
    caps = CAPS[plan]
    return {
        "plan": plan,
        "jobs_processed": {"used": jobs_this_hour, "cap": caps["jobs_hourly"],
                           "resets_at": hour_end.isoformat(), "meter": "hourly"},
        "applications_prepared": {"used": prepared_this_month, "cap": caps["prepared_monthly"],
                                  "resets_at": month_end.isoformat(), "meter": "monthly",
                                  "soft": plan in SOFT_CAP_PLANS},
        "apps_submitted": {"used": submitted_today, "cap": caps["submits_daily"],
                           "resets_at": day_end.isoformat(), "meter": "daily"},
    }

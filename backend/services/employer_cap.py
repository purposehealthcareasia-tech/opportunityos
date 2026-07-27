"""Rolling 30-day per-employer application cap (Phase 3 Founder Brief).

Rationale: high-volume applying is safe as long as we don't spam any one employer.
Each candidate may have at most `EMPLOYER_CAP_PER_30D` non-closed applications for
a single employer (measured by company_name lowercased when company_id is missing,
which is normal for discovery ingest).

The cap is enforced at three natural boundaries:
  * shortlist  → block creation of a 4th open application for the same employer
  * approve    → block re-approval if we've already approved 3 today for that employer
  * submit     → last-mile guard (already covered by receipts uniqueness)

Applications in state="closed" or a receipt-writing terminal state don't count.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from core.db import get_db


EMPLOYER_CAP_PER_30D = 3
CAP_WINDOW_DAYS = 30


def _employer_key(job_or_app: dict) -> Optional[str]:
    """Normalize employer identity across jobs + application snapshots."""
    if job_or_app.get("company_id"):
        return f"cid:{job_or_app['company_id']}"
    # Job doc: company_name at top level; application: job_snapshot.company_name
    name = (job_or_app.get("company_name")
            or (job_or_app.get("job_snapshot") or {}).get("company_name"))
    if not name:
        return None
    return f"cn:{str(name).strip().lower()}"


async def count_recent_for_employer(user_id: str, employer_key: str) -> int:
    """Non-closed applications for this employer created in the last 30 days."""
    if not employer_key:
        return 0
    since = datetime.now(timezone.utc) - timedelta(days=CAP_WINDOW_DAYS)
    q = {
        "user_id": user_id,
        "state": {"$ne": "closed"},
        "created_at": {"$gte": since},
    }
    n = 0
    async for row in get_db().applications.find(q, {"job_snapshot": 1, "company_id": 1, "_id": 0}):
        if _employer_key(row) == employer_key:
            n += 1
    return n


async def check_cap(user_id: str, job: dict) -> dict:
    """Returns {ok:bool, remaining:int, cap:int, employer:str|None}.

    Never raises — callers translate ok=False into a 429 with a specific reason.
    """
    key = _employer_key(job)
    if not key:
        return {"ok": True, "remaining": EMPLOYER_CAP_PER_30D, "cap": EMPLOYER_CAP_PER_30D,
                "employer": None}
    current = await count_recent_for_employer(user_id, key)
    remaining = max(0, EMPLOYER_CAP_PER_30D - current)
    return {
        "ok": current < EMPLOYER_CAP_PER_30D,
        "remaining": remaining,
        "cap": EMPLOYER_CAP_PER_30D,
        "employer": (job.get("company_name")
                     or (job.get("job_snapshot") or {}).get("company_name")),
        "used_last_30d": current,
        "window_days": CAP_WINDOW_DAYS,
    }

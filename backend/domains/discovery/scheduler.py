"""Background scheduler + admin/owner router for manual refresh.

Scheduler:
  * Kicks off inside the FastAPI lifespan when
    DISCOVERY_SCHEDULER_ENABLED=true (default true in preview only).
  * Interval: 6 hours (21600 s). Configurable via
    DISCOVERY_REFRESH_INTERVAL_SECONDS for testing.
  * First run happens ~10s after boot so the app becomes healthy first.

Router (admin-only manual trigger):
  * POST /api/v1/discovery/refresh — runs `refresh_all()` synchronously
    (owner-gated by existing admin dep) and returns the summary.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core.deps import get_current_user
from domains.discovery import service as svc


log = logging.getLogger("oppos.discovery.scheduler")

DEFAULT_INTERVAL_S = 6 * 3600
_task: Optional[asyncio.Task] = None


def _enabled() -> bool:
    return (os.environ.get("DISCOVERY_SCHEDULER_ENABLED", "true").strip().lower()
            in ("1", "true", "yes", "on"))


def _interval_s() -> int:
    try:
        return int(os.environ.get("DISCOVERY_REFRESH_INTERVAL_SECONDS",
                                    str(DEFAULT_INTERVAL_S)))
    except ValueError:
        return DEFAULT_INTERVAL_S


async def _loop():
    initial_delay = float(os.environ.get("DISCOVERY_INITIAL_DELAY_SECONDS", "10"))
    await asyncio.sleep(initial_delay)
    while True:
        try:
            log.info("discovery.scheduler: kick refresh_all")
            await svc.refresh_all(actor="discovery-scheduler")
        except Exception:
            log.exception("discovery.scheduler.refresh failed")
        await asyncio.sleep(_interval_s())


def start_scheduler() -> None:
    global _task
    if _task and not _task.done():
        return
    if not _enabled():
        log.info("discovery.scheduler: disabled by env")
        return
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_loop())
    log.info("discovery.scheduler: task created")


def stop_scheduler() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None


# ---------------------------------------------------------------- router
router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


def _is_admin_or_owner(user: dict) -> bool:
    if not user:
        return False
    if user.get("role") in ("admin", "support"):
        return True
    email = (user.get("email") or "").lower()
    owner_csv = os.environ.get("PRIVATE_AUTOPILOT_OWNER_EMAILS", "")
    owners = {e.strip().lower() for e in owner_csv.split(",") if e.strip()}
    return email in owners


@router.post("/refresh")
async def manual_refresh(user: dict = Depends(get_current_user)):
    """Manually trigger a discovery refresh. Owner / admin / support only."""
    if not _is_admin_or_owner(user):
        raise HTTPException(status_code=403, detail={"error": "admin_or_owner_required"})
    summary = await svc.refresh_all(actor=f"manual:{user.get('id')}")
    return {"ok": True, **summary}


@router.get("/runs")
async def list_runs(user: dict = Depends(get_current_user), limit: int = 20):
    """Return the last N discovery run summaries. Admin/support/owner."""
    if not _is_admin_or_owner(user):
        raise HTTPException(status_code=403, detail={"error": "admin_or_owner_required"})
    from core.db import get_db
    cur = get_db().discovery_runs.find({}, projection={"_id": 0}).sort("ts", -1).limit(limit)
    rows = [r async for r in cur]
    return {"rows": rows}

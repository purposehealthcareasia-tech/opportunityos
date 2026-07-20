from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from core.db import get_db
from core.deps import get_current_user

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


def _period() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


async def increment_jobs_processed(user_id: str, amount: int = 1) -> None:
    if amount <= 0:
        return
    db = get_db()
    await db.usage_meters.update_one(
        {"user_id": user_id, "period": _period()},
        {"$inc": {"jobs_processed": amount},
         "$setOnInsert": {"user_id": user_id, "period": _period(), "apps_prepared": 0, "apps_submitted": 0}},
        upsert=True,
    )


async def increment_apps_prepared(user_id: str, amount: int = 1) -> None:
    db = get_db()
    await db.usage_meters.update_one(
        {"user_id": user_id, "period": _period()},
        {"$inc": {"apps_prepared": amount},
         "$setOnInsert": {"user_id": user_id, "period": _period(), "jobs_processed": 0, "apps_submitted": 0}},
        upsert=True,
    )


async def increment_apps_submitted(user_id: str, amount: int = 1) -> None:
    db = get_db()
    await db.usage_meters.update_one(
        {"user_id": user_id, "period": _period()},
        {"$inc": {"apps_submitted": amount},
         "$setOnInsert": {"user_id": user_id, "period": _period(), "jobs_processed": 0, "apps_prepared": 0}},
        upsert=True,
    )


@router.get("/me")
async def get_usage(user: dict = Depends(get_current_user)):
    doc = await get_db().usage_meters.find_one({"user_id": user["id"], "period": _period()}, {"_id": 0})
    return doc or {"user_id": user["id"], "period": _period(), "jobs_processed": 0, "apps_prepared": 0, "apps_submitted": 0}

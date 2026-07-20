from core.db import get_db


async def latest_for_user(user_id: str) -> dict | None:
    return await get_db().eligibility_profiles.find_one({"user_id": user_id}, sort=[("version", -1)])


async def next_version(user_id: str) -> int:
    latest = await latest_for_user(user_id)
    return (latest.get("version", 0) if latest else 0) + 1


async def insert(doc: dict) -> None:
    await get_db().eligibility_profiles.insert_one(doc)


async def live_jobs() -> list[dict]:
    from core.db import get_db as _db
    cur = _db().jobs.find({"status": "live"}, {"_id": 0})
    return [j async for j in cur]

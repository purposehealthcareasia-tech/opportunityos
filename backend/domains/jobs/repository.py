from core.db import get_db


async def by_id(job_id: str) -> dict | None:
    return await get_db().jobs.find_one({"id": job_id}, {"_id": 0})


async def by_canonical(key: str) -> dict | None:
    return await get_db().jobs.find_one({"canonical_key": key}, {"_id": 0})


async def insert(doc: dict) -> None:
    await get_db().jobs.insert_one(doc)


async def update_by_key(key: str, updates: dict) -> None:
    await get_db().jobs.update_one({"canonical_key": key}, {"$set": updates})


async def append_also_seen(key: str, url: str) -> None:
    await get_db().jobs.update_one({"canonical_key": key}, {"$addToSet": {"also_seen": url}})


async def list_live() -> list[dict]:
    cur = get_db().jobs.find({"status": "live"}, {"_id": 0})
    return [j async for j in cur]


async def list_derived_for_user(user_id: str) -> list[dict]:
    cur = get_db().jobs.find({"status": "derived", "imported_by": user_id}, {"_id": 0}).sort("first_seen", -1)
    return [j async for j in cur]


async def hidden_for_user(user_id: str) -> list[dict]:
    cur = get_db().hidden_jobs.find({"user_id": user_id}, {"_id": 0})
    return [h async for h in cur]


async def add_hidden(user_id: str, job_id: str, reason: str) -> None:
    from core.time_utils import utc_now
    import uuid
    await get_db().hidden_jobs.update_one(
        {"user_id": user_id, "job_id": job_id},
        {"$set": {"reason": reason, "ts": utc_now()},
         "$setOnInsert": {"id": str(uuid.uuid4()), "user_id": user_id, "job_id": job_id}},
        upsert=True,
    )

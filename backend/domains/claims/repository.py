from core.db import get_db


async def by_id_for_user(claim_id: str, user_id: str) -> dict | None:
    return await get_db().claims.find_one({"id": claim_id, "user_id": user_id})


async def insert_many(docs: list[dict]) -> int:
    if not docs:
        return 0
    res = await get_db().claims.insert_many(docs)
    return len(res.inserted_ids)


async def insert_one(doc: dict) -> None:
    await get_db().claims.insert_one(doc)


async def update_fields(claim_id: str, updates: dict) -> None:
    await get_db().claims.update_one({"id": claim_id}, {"$set": updates})


async def list_for_user(user_id: str, *, include_history: bool = False) -> list[dict]:
    q: dict = {"user_id": user_id}
    if not include_history:
        q["superseded_by"] = None
    cur = get_db().claims.find(q, {"_id": 0}).sort([("type", 1), ("created_at", 1)])
    return [c async for c in cur]


async def pending_ids(user_id: str, ctype: str | None = None) -> list[str]:
    q: dict = {"user_id": user_id, "status": "pending", "superseded_by": None}
    if ctype:
        q["type"] = ctype
    cur = get_db().claims.find(q, {"id": 1, "_id": 0})
    return [c["id"] async for c in cur]


async def approved_types(user_id: str) -> set[str]:
    cur = get_db().claims.find(
        {"user_id": user_id, "status": "approved", "superseded_by": None},
        {"type": 1, "_id": 0},
    )
    return {c["type"] async for c in cur}

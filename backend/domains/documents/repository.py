from core.db import get_db
from core.time_utils import utc_now


async def insert(doc: dict) -> None:
    await get_db().documents.insert_one(doc)


async def by_id_for_user(doc_id: str, user_id: str) -> dict | None:
    return await get_db().documents.find_one({"id": doc_id, "user_id": user_id})


async def list_for_user(user_id: str) -> list[dict]:
    cur = get_db().documents.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1)
    return [d async for d in cur]


async def update_parse_status(doc_id: str, *, status: str, error: str | None = None, meta: dict | None = None) -> None:
    updates: dict = {"parse_status": status, "updated_at": utc_now()}
    if error is not None:
        updates["parse_error"] = error
    if meta is not None:
        updates["parse_meta"] = meta
    await get_db().documents.update_one({"id": doc_id}, {"$set": updates})


async def by_sha_for_user(sha: str, user_id: str) -> dict | None:
    return await get_db().documents.find_one({"user_id": user_id, "sha256": sha, "kind": "resume"})

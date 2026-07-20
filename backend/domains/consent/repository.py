import uuid
from core.db import get_db
from core.time_utils import utc_now


async def append(row_data: dict) -> str:
    row = {
        "id": str(uuid.uuid4()),
        "ts": utc_now(),
        **row_data,
    }
    await get_db().consent_records.insert_one(row)
    return row["id"]


async def latest_for_scope(user_id: str, scope: str) -> dict | None:
    return await get_db().consent_records.find_one(
        {"user_id": user_id, "scope": scope}, sort=[("ts", -1)]
    )


async def latest_all(user_id: str) -> dict[str, dict]:
    """Return {scope: latest_row} across every scope the user has ever touched."""
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$sort": {"ts": -1}},
        {"$group": {"_id": "$scope", "row": {"$first": "$$ROOT"}}},
    ]
    out: dict[str, dict] = {}
    async for doc in get_db().consent_records.aggregate(pipeline):
        row = doc["row"]
        row.pop("_id", None)
        out[doc["_id"]] = row
    return out

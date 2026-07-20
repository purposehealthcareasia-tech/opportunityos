import uuid
from typing import Any
from core.db import get_db
from core.time_utils import utc_now


async def write(actor: str, action: str, object_ref: str, meta: dict[str, Any] | None = None) -> str:
    """APPEND-ONLY. Never update, never delete. Returns the audit row id."""
    row = {
        "id": str(uuid.uuid4()),
        "actor": actor,
        "action": action,
        "object_ref": object_ref,
        "ts": utc_now(),
        "meta": meta or {},
    }
    await get_db().audit_logs.insert_one(row)
    return row["id"]


async def list_for_actor(actor: str, limit: int = 100) -> list[dict]:
    cur = get_db().audit_logs.find({"actor": actor}, {"_id": 0}).sort("ts", -1).limit(limit)
    return [doc async for doc in cur]

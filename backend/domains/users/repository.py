from core.db import get_db


async def get_claims_for_user(user_id: str) -> list[dict]:
    cur = get_db().claims.find({"user_id": user_id, "superseded_by": None}).sort("type", 1)
    return [doc async for doc in cur]

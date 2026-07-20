from typing import Any
from core.db import get_db


async def by_email(email: str) -> dict | None:
    return await get_db().users.find_one({"email": email.lower()})


async def by_id(user_id: str) -> dict | None:
    return await get_db().users.find_one({"id": user_id})


async def create(doc: dict[str, Any]) -> None:
    await get_db().users.insert_one(doc)


async def update_password(user_id: str, new_hash: str) -> None:
    await get_db().users.update_one({"id": user_id}, {"$set": {"password_hash": new_hash}})


async def update_profile(user_id: str, updates: dict) -> None:
    if updates:
        await get_db().users.update_one({"id": user_id}, {"$set": updates})

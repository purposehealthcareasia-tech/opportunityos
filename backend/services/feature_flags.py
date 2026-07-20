"""Feature-flag runtime helper. Reads from `feature_flags` collection with a 60s cache.
The founder brief requires flag flips to take effect ≤60s (spec §C.4)."""
from __future__ import annotations
import asyncio
import time
from core.db import get_db


_CACHE: dict[str, tuple[bool, float]] = {}
_TTL = 60  # seconds — spec §C.4


async def is_enabled(name: str, default: bool = True) -> bool:
    now = time.monotonic()
    cached = _CACHE.get(name)
    if cached and (now - cached[1]) < _TTL:
        return cached[0]
    row = await get_db().feature_flags.find_one({"name": name}, {"_id": 0, "enabled": 1})
    val = bool(row["enabled"]) if row else default
    _CACHE[name] = (val, now)
    return val


def invalidate(name: str | None = None) -> None:
    if name is None:
        _CACHE.clear()
    else:
        _CACHE.pop(name, None)

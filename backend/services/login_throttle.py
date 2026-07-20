"""SEC-P3(a) · Login-brute-force throttle.

Two independent buckets are enforced; the FIRST to fill triggers a 429:

  - Per (route, identifier)  — catches account guessing / credential stuffing.
    Window `IDENTIFIER_WINDOW_SECONDS` (default 300 s); max
    `IDENTIFIER_MAX_ATTEMPTS` (default 10).
  - Per (route, ip)          — catches IP-wide signup/login floods regardless
    of the identifier used. Window `IP_WINDOW_SECONDS` (default 300 s); max
    `IP_MAX_ATTEMPTS` (default 30 — generous enough to survive k8s ingress
    round-robin across pods).

Successful auth clears the identifier bucket so one legit login after typos
doesn't leave a punitive counter. The IP bucket is never cleared.
"""
from __future__ import annotations

from datetime import timedelta
from fastapi import HTTPException, Request
from starlette import status

from core.db import get_db
from core.time_utils import utc_now


IDENTIFIER_WINDOW_SECONDS = 300
IDENTIFIER_MAX_ATTEMPTS = 10
IP_WINDOW_SECONDS = 300
IP_MAX_ATTEMPTS = 30


def _ip(request: Request) -> str:
    # k8s ingress obscures the socket IP; prefer X-Forwarded-For (first hop =
    # original client) when present so throttling isn't defeated by
    # round-robin across pod IPs.
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else None) or "unknown"


def _naive(dt):
    if dt is None:
        return dt
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt


async def _check_bucket(db, key: dict, window: int, cap: int, now, cutoff) -> None:
    """Read attempts, trim expired, block if cap reached, else record `now`."""
    doc = await db.login_throttle.find_one(key) or {}
    attempts = [_naive(a) for a in (doc.get("attempts") or []) if _naive(a) >= cutoff]
    if len(attempts) >= cap:
        oldest = min(attempts)
        retry_after = int((oldest + timedelta(seconds=window) - now).total_seconds()) + 1
        retry_after = max(retry_after, 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limited",
                "message": f"Too many attempts. Try again in {retry_after}s.",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    attempts.append(now)
    await db.login_throttle.update_one(
        key,
        {"$set": {**key, "attempts": attempts, "updated_at": now}},
        upsert=True,
    )


async def check_and_record_attempt(request: Request, route: str, identifier: str) -> None:
    """Register a fresh attempt for both (route, identifier) AND (route, ip).
    Either bucket over its cap → 429. Call this BEFORE crypto verify so
    brute-force guessers get counted on every attempt."""
    db = get_db()
    now = _naive(utc_now())
    ident = (identifier or "").lower()
    ip = _ip(request)

    id_cutoff = now - timedelta(seconds=IDENTIFIER_WINDOW_SECONDS)
    ip_cutoff = now - timedelta(seconds=IP_WINDOW_SECONDS)

    await _check_bucket(
        db, {"route": route, "identifier": ident, "ip": None},
        IDENTIFIER_WINDOW_SECONDS, IDENTIFIER_MAX_ATTEMPTS, now, id_cutoff,
    )
    await _check_bucket(
        db, {"route": route, "identifier": None, "ip": ip},
        IP_WINDOW_SECONDS, IP_MAX_ATTEMPTS, now, ip_cutoff,
    )


async def clear_bucket(request: Request, route: str, identifier: str) -> None:
    """Called after a successful auth event — removes only the identifier
    bucket. IP bucket is NOT cleared: a burst script gets its cooldown either
    way."""
    db = get_db()
    await db.login_throttle.delete_one({
        "route": route,
        "identifier": (identifier or "").lower(),
        "ip": None,
    })


async def ensure_indexes() -> None:
    db = get_db()
    await db.login_throttle.create_index(
        [("route", 1), ("identifier", 1), ("ip", 1)], unique=True,
    )
    await db.login_throttle.create_index("updated_at", expireAfterSeconds=86400)

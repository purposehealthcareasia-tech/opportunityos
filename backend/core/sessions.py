"""Phase 6 · Server-side session store.

Sessions live in MongoDB (`sessions` collection) so logout / role-change /
manual revocation actually invalidate the credential — an opaque cookie value
that isn't self-verifying like a JWT.

Every login writes a row; every logout revokes; role change → new session id
(rotation, defence against session fixation).

Also produces a per-session CSRF token consumed by the double-submit CSRF
middleware.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from core.config import settings
from core.db import get_db
from core.time_utils import utc_now


def _new_id() -> str:
    """Opaque, unforgeable session id — 256 random bits, URL-safe."""
    return secrets.token_urlsafe(32)


def _new_csrf() -> str:
    return secrets.token_urlsafe(32)


async def create_session(user_id: str, role: str, ip: str | None = None,
                          user_agent: str | None = None) -> dict:
    """Insert a fresh session row. Returns the new session doc."""
    now = utc_now()
    exp = now + timedelta(hours=settings.SESSION_TTL_HOURS)
    doc = {
        "session_id": _new_id(),
        "csrf_token": _new_csrf(),
        "user_id": user_id,
        "role": role or "user",
        "created_at": now,
        "expires_at": exp,
        "revoked_at": None,
        "last_seen_at": now,
        "ip": ip,
        "user_agent": user_agent,
    }
    await get_db().sessions.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def get_session(session_id: str) -> dict | None:
    """Return the session row iff it is not revoked and not expired."""
    if not session_id:
        return None
    now = utc_now()
    row = await get_db().sessions.find_one(
        {"session_id": session_id, "revoked_at": None, "expires_at": {"$gt": now}},
        {"_id": 0},
    )
    if row:
        # Touch last_seen; not awaited (fire-and-forget would break motor typing) — keep sync.
        await get_db().sessions.update_one(
            {"session_id": session_id}, {"$set": {"last_seen_at": now}},
        )
    return row


async def revoke_session(session_id: str) -> None:
    if not session_id:
        return
    await get_db().sessions.update_one(
        {"session_id": session_id, "revoked_at": None},
        {"$set": {"revoked_at": utc_now()}},
    )


async def revoke_all_for_user(user_id: str) -> int:
    """Used by role change / delete-account."""
    r = await get_db().sessions.update_many(
        {"user_id": user_id, "revoked_at": None},
        {"$set": {"revoked_at": utc_now()}},
    )
    return r.modified_count


async def rotate_session(old_session_id: str, new_role: str | None = None) -> dict | None:
    """Revoke the current session and mint a new one for the same user.
    Called on role change (or as an anti-fixation measure on login)."""
    db = get_db()
    existing = await db.sessions.find_one({"session_id": old_session_id}, {"_id": 0})
    if not existing:
        return None
    await revoke_session(old_session_id)
    return await create_session(
        user_id=existing["user_id"],
        role=new_role or existing.get("role", "user"),
        ip=existing.get("ip"),
        user_agent=existing.get("user_agent"),
    )


async def ensure_session_indexes() -> None:
    db = get_db()
    await db.sessions.create_index("session_id", unique=True)
    await db.sessions.create_index("user_id")
    # TTL sweep — MongoDB will remove rows once `expires_at` passes.
    await db.sessions.create_index("expires_at", expireAfterSeconds=0)


def cookie_kwargs_for_role(role: str) -> dict[str, Any]:
    """Cookie flags for the given role.
    - user  → SameSite=Lax
    - admin/support → SameSite=Strict
    All get httpOnly + Secure (in preview/prod).
    """
    samesite = (settings.SESSION_COOKIE_SAMESITE_ADMIN
                if role in {"admin", "support"}
                else settings.SESSION_COOKIE_SAMESITE_USER)
    return {
        "httponly": True,
        "secure": bool(settings.SESSION_COOKIE_SECURE),
        "samesite": samesite,
        "max_age": settings.SESSION_TTL_HOURS * 3600,
        "path": "/",
    }

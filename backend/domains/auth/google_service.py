"""Google Sign-In service — Emergent-managed OAuth (Milestone E).

Flow:
  1. Frontend redirects to `https://auth.emergentagent.com/?redirect=<url>`.
  2. Google callback lands at `<url>#session_id=<sid>` on the frontend.
  3. Frontend POSTs `{session_id}` to `/api/v1/auth/google/session`.
  4. Backend exchanges the session_id with Emergent's session-data endpoint
     (server-to-server; the id_token / access_token NEVER touch the client).
  5. If a user with that email already exists → log them in with a fresh
     `oppos_session` cookie and record `auth.google_login`.
  6. Otherwise → create a short-lived `pending_google_signups` row and
     return {pending_signup_id, email, name, picture} — the frontend must
     collect the 5-scope consent UI and POST `/api/v1/auth/google/complete`.

Consent-first invariant: NO user row is created until the consent scopes
have been submitted at step 6.

Sensitive material NEVER exposed by the API surface:
  - `google_id_token`, `google_access_token`, `google_refresh_token`,
    `emergent_session_token` — none are stored or returned.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta
from typing import Any, Optional

import httpx
from fastapi import HTTPException, Request, Response, status

from core.config import settings
from core.db import get_db
from core.policy import REQUIRED_SCOPES, SCOPE_KEYS
from core.time_utils import utc_now
from core import sessions as session_store
from services import login_throttle
from domains.auth import repository as user_repo
from domains.audit import service as audit
from domains.consent import service as consent_svc


log = logging.getLogger("oppos.auth.google")


EMERGENT_SESSION_DATA_URL = (
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
)
PENDING_TTL_MINUTES = 15


def _build_bearer_body(user_id: str) -> dict:
    """Match the existing password-login response shape: only include a bearer
    token when the CI issuer flag is on."""
    from domains.auth.service import _maybe_bearer_body  # local import — avoids cycles
    return _maybe_bearer_body(user_id)


def _set_session_cookies(response: Response, session_row: dict, role: str) -> None:
    from domains.auth.service import _set_session_cookies as _set  # single source of truth
    _set(response, session_row, role)


async def ensure_indexes() -> None:
    db = get_db()
    # linked_auth_identities: unique (provider, provider_user_id); unique
    # (provider, email) — so at most ONE Google account can map to a given
    # OpportunityOS email per provider.
    await db.linked_auth_identities.create_index(
        [("provider", 1), ("provider_user_id", 1)], unique=True,
    )
    await db.linked_auth_identities.create_index(
        [("provider", 1), ("email", 1)], unique=True,
    )
    await db.linked_auth_identities.create_index("user_id")
    # pending_google_signups: TTL of PENDING_TTL_MINUTES.
    await db.pending_google_signups.create_index(
        "expires_at", expireAfterSeconds=0,
    )
    await db.pending_google_signups.create_index("id", unique=True)


async def _fetch_emergent_session_data(session_id: str) -> dict[str, Any]:
    """Server-to-server exchange with Emergent's session-data endpoint."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                EMERGENT_SESSION_DATA_URL,
                headers={"X-Session-ID": session_id},
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail={
            "error": "emergent_auth_unreachable", "message": str(e)[:200],
        })
    if r.status_code in (401, 404):
        raise HTTPException(status_code=401, detail={
            "error": "google_session_invalid",
            "message": "Session id is invalid or expired. Please retry sign-in.",
        })
    if not r.is_success:
        log.warning("Emergent session-data non-2xx: HTTP %s", r.status_code)
        raise HTTPException(status_code=400, detail={
            "error": "emergent_auth_error", "message": f"upstream HTTP {r.status_code}",
        })
    body = r.json()
    # Expected keys: id, email, name, picture, session_token
    if not body.get("email") or not body.get("id"):
        raise HTTPException(status_code=502, detail={
            "error": "emergent_auth_malformed", "message": "missing id/email in response",
        })
    return body


async def start_google_session(
    *, session_id: str, request: Request, response: Response,
) -> dict[str, Any]:
    """Step 3 of the flow. Exchange session_id with Emergent, then either
    log in an existing user OR return a pending-signup handle."""
    if not session_id or len(session_id) > 200:
        raise HTTPException(status_code=400, detail={"error": "bad_session_id"})

    # Rate-limit by IP so a stolen session_id can't be replayed at high rate.
    await login_throttle.check_and_record_attempt(request, "google_session", session_id[:32])

    data = await _fetch_emergent_session_data(session_id)
    email = (data["email"] or "").lower()
    provider_user_id = data["id"]
    name = (data.get("name") or "").strip() or email.split("@")[0]
    picture = data.get("picture")

    db = get_db()

    # 1) A prior link exists → log in the linked OpportunityOS user.
    link = await db.linked_auth_identities.find_one({
        "provider": "google", "provider_user_id": provider_user_id,
    })
    user = None
    if link:
        user = await user_repo.by_id(link["user_id"])

    # 2) No link yet but a user with the same email exists → link + log in.
    #    (Consent-first still holds: the user already granted required scopes
    #    at their original signup, and we're merely attaching an identity.)
    if not user:
        u = await user_repo.by_email(email)
        if u:
            user = u
            await db.linked_auth_identities.insert_one({
                "id": str(uuid.uuid4()),
                "provider": "google",
                "provider_user_id": provider_user_id,
                "email": email,
                "user_id": u["id"],
                "linked_at": utc_now(),
            })
            await audit.write(u["id"], "auth.account_link",
                               f"user:{u['id']}",
                               {"provider": "google", "email": email})

    if user:
        # Log in path. Refuse soft-deleted accounts (parity with password login).
        if user.get("deletion_pending_at"):
            raise HTTPException(status_code=403, detail={
                "error": "account_deletion_pending",
                "message": "This account is pending deletion.",
            })
        admin_row = await db.admin_users.find_one({"user_id": user["id"]})
        role = admin_row["role"] if admin_row else "user"

        session_row = await session_store.create_session(
            user_id=user["id"],
            role=role,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        _set_session_cookies(response, session_row, role)
        await login_throttle.clear_bucket(request, "google_session", session_id[:32])
        await audit.write(user["id"], "auth.google_login",
                           f"session:{session_row['session_id']}",
                           {"provider": "google", "role": role})
        return {
            "status": "logged_in",
            **_build_bearer_body(user["id"]),
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "role": role,
                "passport_activated": user.get("passport_activated", False),
                "created_at": user["created_at"],
            },
        }

    # 3) New user. Create a pending_google_signups row and return its id.
    pending_id = str(uuid.uuid4())
    now = utc_now()
    await db.pending_google_signups.insert_one({
        "id": pending_id,
        "provider": "google",
        "provider_user_id": provider_user_id,
        "email": email,
        "name": name,
        "picture": picture,
        "created_at": now,
        "expires_at": now + timedelta(minutes=PENDING_TTL_MINUTES),
    })
    await audit.write(email, "auth.google_pending_signup",
                       f"pending:{pending_id}",
                       {"provider": "google"})
    return {
        "status": "pending_consent",
        "pending_signup_id": pending_id,
        "email": email,
        "name": name,
        "picture": picture,
        "consent_scopes": list(SCOPE_KEYS),
        "required_scopes": list(REQUIRED_SCOPES),
        "expires_at": (now + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat(),
    }


async def complete_google_signup(
    *, pending_signup_id: str, consents: dict[str, bool],
    policy_text_version: str, request: Request, response: Response,
) -> dict[str, Any]:
    db = get_db()
    pending = await db.pending_google_signups.find_one({"id": pending_signup_id})
    if not pending:
        raise HTTPException(status_code=404, detail={
            "error": "pending_signup_not_found",
            "message": "Pending Google signup expired or does not exist. Restart sign-in.",
        })
    # TTL is enforced by Mongo, but double-check for clock skew.
    exp = pending.get("expires_at")
    if exp is not None:
        exp_naive = exp.replace(tzinfo=None) if hasattr(exp, "replace") and getattr(exp, "tzinfo", None) else exp
        now_naive = utc_now().replace(tzinfo=None)
        if exp_naive < now_naive:
            raise HTTPException(status_code=410, detail={"error": "pending_signup_expired"})

    email = pending["email"]

    # Enforce required scopes.
    for scope in REQUIRED_SCOPES:
        if not consents.get(scope):
            raise HTTPException(status_code=400, detail={
                "error": "required_consent_missing", "scope": scope,
            })

    # Race: user could have been created via password since we started.
    existing = await user_repo.by_email(email)
    if existing:
        user_id = existing["id"]
    else:
        user_id = str(uuid.uuid4())
        now = utc_now()
        await user_repo.create({
            "id": user_id,
            "email": email,
            # No password_hash — this is a Google-linked account until the
            # user sets a password.
            "password_hash": "",
            "name": pending["name"],
            "passport_activated": False,
            "created_at": now,
        })
        await audit.write(user_id, "auth.google_signup", f"user:{user_id}",
                           {"email": email, "provider": "google"})

    # Persist link (idempotent).
    await db.linked_auth_identities.update_one(
        {"provider": "google", "provider_user_id": pending["provider_user_id"]},
        {"$set": {
            "provider": "google",
            "provider_user_id": pending["provider_user_id"],
            "email": email,
            "user_id": user_id,
            "linked_at": utc_now(),
        }, "$setOnInsert": {"id": str(uuid.uuid4())}},
        upsert=True,
    )

    # Consent ledger: record every scope the client sent.
    for scope, granted in consents.items():
        if scope not in SCOPE_KEYS:
            continue
        await consent_svc.record(
            user_id=user_id,
            scope=scope,
            granted=bool(granted),
            policy_text_version=policy_text_version,
            actor=user_id,
            source="google_signup",
        )

    # Remove the pending row so it cannot be re-used.
    await db.pending_google_signups.delete_one({"id": pending_signup_id})

    admin_row = await db.admin_users.find_one({"user_id": user_id})
    role = admin_row["role"] if admin_row else "user"
    session_row = await session_store.create_session(
        user_id=user_id, role=role,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(response, session_row, role)
    await audit.write(user_id, "auth.session_created",
                       f"session:{session_row['session_id']}",
                       {"via": "google_signup", "role": role})

    return {
        "status": "signed_up",
        **_build_bearer_body(user_id),
        "user": {
            "id": user_id,
            "email": email,
            "name": pending["name"],
            "role": role,
            "passport_activated": False,
        },
    }

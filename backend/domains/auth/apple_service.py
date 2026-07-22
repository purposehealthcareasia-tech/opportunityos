"""Sign in with Apple — standards-based OIDC service.

Playbook conformance:
  - Authorization code flow with `response_mode=form_post`, `scope=name email`.
  - ES256 client-secret JWT built at request time (never persisted).
  - Apple `id_token` verified against JWKS (`https://appleid.apple.com/auth/keys`),
    with issuer + audience + nonce claims strictly checked.
  - State (CSRF) + nonce (replay) tracked server-side in `apple_auth_states`;
    single-use, TTL 10 min.
  - Consent-first invariant preserved — no `users` row is created until the
    5-scope consent UI is submitted at `/complete`.
  - Private-relay emails (`@privaterelay.appleid.com`) are NEVER auto-linked to
    an existing account by email. The user is offered explicit manual linking
    from Settings after verified logins to both accounts.

Sensitive material NEVER exposed by the API surface:
  - APPLE_PRIVATE_KEY, client-secret JWT, id_token, access_token, refresh_token.

Failure mapping:
  - CONFIGURATION_REQUIRED → 503 with `{error: "apple_auth_not_configured"}`.
  - Missing/invalid state → 400 `{error: "apple_state_invalid"}`.
  - Token exchange upstream failure → 502 `{error: "apple_token_exchange_failed"}`.
  - id_token signature / nonce / iss / aud failure → 401 `{error: "apple_id_token_invalid"}`.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from datetime import timedelta
from typing import Any, Optional

import httpx
import jwt
from fastapi import HTTPException, Request, Response
from jwt.algorithms import ECAlgorithm

from core.db import get_db
from core.policy import REQUIRED_SCOPES, SCOPE_KEYS
from core.time_utils import utc_now
from core import sessions as session_store
from services import login_throttle
from domains.auth import repository as user_repo
from domains.audit import service as audit
from domains.consent import service as consent_svc


log = logging.getLogger("oppos.auth.apple")


APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
PRIVATE_RELAY_DOMAIN = "@privaterelay.appleid.com"

STATE_TTL_MINUTES = 10
PENDING_TTL_MINUTES = 15
_JWKS_CACHE: dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Configuration helpers (READ ONLY — never expose values).
# ---------------------------------------------------------------------------

def _cfg() -> dict[str, str]:
    return {k: os.environ.get(k, "") for k in (
        "APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID",
        "APPLE_PRIVATE_KEY", "APPLE_REDIRECT_URI", "APPLE_AUTH_ENABLED",
    )}


def _is_configured() -> bool:
    c = _cfg()
    required = ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID",
                "APPLE_PRIVATE_KEY", "APPLE_REDIRECT_URI")
    if not all(c.get(k) for k in required):
        return False
    if not c["APPLE_REDIRECT_URI"].startswith("https://"):
        return False
    enabled = (c.get("APPLE_AUTH_ENABLED") or "true").lower()
    if enabled in ("0", "false", "off"):
        return False
    return True


def _require_configured() -> dict[str, str]:
    if not _is_configured():
        raise HTTPException(status_code=503, detail={
            "error": "apple_auth_not_configured",
            "message": "Sign in with Apple is not yet configured on this server.",
        })
    return _cfg()


# ---------------------------------------------------------------------------
# ES256 client-secret JWT (built at request time; never persisted).
# ---------------------------------------------------------------------------

def _client_secret_jwt(cfg: dict[str, str]) -> str:
    now = int(time.time())
    private_key = cfg["APPLE_PRIVATE_KEY"].replace("\\n", "\n")
    payload = {
        "iss": cfg["APPLE_TEAM_ID"],
        "iat": now,
        "exp": now + 60 * 30,          # short-lived — 30 min max
        "aud": APPLE_ISSUER,
        "sub": cfg["APPLE_CLIENT_ID"],
    }
    headers = {"alg": "ES256", "kid": cfg["APPLE_KEY_ID"]}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


# ---------------------------------------------------------------------------
# id_token verification via Apple JWKS.
# ---------------------------------------------------------------------------

async def _fetch_apple_jwks() -> list[dict]:
    now = time.time()
    if _JWKS_CACHE["keys"] and (now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL_SECONDS):
        return _JWKS_CACHE["keys"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(APPLE_JWKS_URL)
        r.raise_for_status()
        keys = r.json()["keys"]
    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["fetched_at"] = now
    return keys


async def _verify_apple_id_token(id_token: str, *, expected_nonce: str,
                                  expected_aud: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "unreadable header"})
    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "missing kid"})

    try:
        keys = await _fetch_apple_jwks()
    except Exception:
        raise HTTPException(status_code=502, detail={"error": "apple_jwks_unreachable"})
    jwk = next((k for k in keys if k.get("kid") == kid), None)
    if not jwk:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "unknown kid"})

    try:
        public_key = ECAlgorithm.from_jwk(json.dumps(jwk))
        payload = jwt.decode(
            id_token,
            public_key,
            algorithms=["ES256"],
            audience=expected_aud,
            issuer=APPLE_ISSUER,
        )
    except jwt.InvalidSignatureError:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "signature"})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "expired"})
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "audience"})
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "issuer"})
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": str(e)[:100]})

    if payload.get("nonce") != expected_nonce:
        raise HTTPException(status_code=401, detail={"error": "apple_id_token_invalid",
                                                     "message": "nonce"})
    return payload


# ---------------------------------------------------------------------------
# State store — CSRF + nonce, TTL 10 min, single-use.
# ---------------------------------------------------------------------------

async def ensure_indexes() -> None:
    db = get_db()
    await db.apple_auth_states.create_index("state", unique=True)
    await db.apple_auth_states.create_index("expires_at", expireAfterSeconds=0)
    await db.pending_apple_signups.create_index("id", unique=True)
    await db.pending_apple_signups.create_index("expires_at", expireAfterSeconds=0)
    # `linked_auth_identities` indexes already exist via google_service.ensure_indexes.


async def _put_state(state: str, nonce: str) -> None:
    now = utc_now()
    await get_db().apple_auth_states.insert_one({
        "state": state,
        "nonce": nonce,
        "created_at": now,
        "expires_at": now + timedelta(minutes=STATE_TTL_MINUTES),
    })


async def _consume_state(state: str) -> Optional[str]:
    """Return the associated nonce and delete the row (single-use)."""
    row = await get_db().apple_auth_states.find_one_and_delete({"state": state})
    if not row:
        return None
    return row.get("nonce")


# ---------------------------------------------------------------------------
# Flow entry points.
# ---------------------------------------------------------------------------

async def build_authorize_url(request: Request) -> dict[str, Any]:
    """Return `{authorize_url, state}` for the frontend to navigate to."""
    cfg = _require_configured()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    await _put_state(state, nonce)

    params = {
        "response_type": "code",
        "response_mode": "form_post",
        "client_id": cfg["APPLE_CLIENT_ID"],
        "redirect_uri": cfg["APPLE_REDIRECT_URI"],
        "scope": "name email",
        "state": state,
        "nonce": nonce,
    }
    from urllib.parse import urlencode
    return {"authorize_url": f"{APPLE_AUTH_URL}?{urlencode(params)}", "state": state}


async def handle_callback(*, code: str, state: str, id_token_body: Optional[str],
                          user_json: Optional[str], request: Request,
                          response: Response) -> dict[str, Any]:
    """Apple form_post callback — POST body carries {code, state, id_token?, user?}.

    Returns either `{status: "logged_in", user, ...}` or
    `{status: "pending_consent", pending_signup_id, email, is_private_email}`.
    """
    cfg = _require_configured()

    if not code or not state:
        raise HTTPException(status_code=400, detail={"error": "apple_callback_missing_params"})
    await login_throttle.check_and_record_attempt(request, "apple_callback", state[:32])

    expected_nonce = await _consume_state(state)
    if not expected_nonce:
        raise HTTPException(status_code=400, detail={"error": "apple_state_invalid"})

    # 1) Exchange code for tokens.
    client_secret = _client_secret_jwt(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(APPLE_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg["APPLE_REDIRECT_URI"],
                "client_id": cfg["APPLE_CLIENT_ID"],
                "client_secret": client_secret,
            })
        except Exception as e:
            raise HTTPException(status_code=502, detail={
                "error": "apple_token_exchange_failed", "message": str(e)[:200],
            })
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail={
            "error": "apple_token_exchange_failed",
            "message": f"upstream HTTP {r.status_code}",
        })
    token_body = r.json()
    id_token = token_body.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail={"error": "apple_token_missing_id_token"})

    # 2) Verify id_token.
    payload = await _verify_apple_id_token(
        id_token, expected_nonce=expected_nonce, expected_aud=cfg["APPLE_CLIENT_ID"],
    )
    apple_sub = payload["sub"]
    email = (payload.get("email") or "").lower().strip()
    is_private_email = bool(payload.get("is_private_email")) or email.endswith(PRIVATE_RELAY_DOMAIN)
    email_verified = payload.get("email_verified") in (True, "true", 1, "1")

    # Apple only sends `user_json` (containing full name) on FIRST auth. If
    # present, extract a display name; otherwise fall back to email prefix.
    parsed_name = ""
    if user_json:
        try:
            u = json.loads(user_json)
            name_obj = u.get("name") or {}
            parsed_name = f"{name_obj.get('firstName', '')} {name_obj.get('lastName', '')}".strip()
        except Exception:
            parsed_name = ""

    return await _finalize_apple_identity(
        apple_sub=apple_sub, email=email, name=parsed_name,
        is_private_email=is_private_email, email_verified=email_verified,
        request=request, response=response,
    )


async def _finalize_apple_identity(*, apple_sub: str, email: str, name: str,
                                    is_private_email: bool, email_verified: bool,
                                    request: Request, response: Response) -> dict[str, Any]:
    db = get_db()

    # 1) A prior Apple link exists → log in the linked user (irrespective of email).
    link = await db.linked_auth_identities.find_one({
        "provider": "apple", "provider_user_id": apple_sub,
    })
    user = None
    if link:
        user = await user_repo.by_id(link["user_id"])

    # 2) No link. Auto-link by email ONLY when:
    #    (a) email is non-empty, verified by Apple, AND
    #    (b) NOT a private-relay address (founder amendment).
    if not user and email and email_verified and not is_private_email:
        candidate = await user_repo.by_email(email)
        if candidate:
            user = candidate
            await db.linked_auth_identities.insert_one({
                "id": str(uuid.uuid4()),
                "provider": "apple",
                "provider_user_id": apple_sub,
                "email": email,
                "user_id": candidate["id"],
                "linked_at": utc_now(),
                "is_private_email": False,
            })
            await audit.write(candidate["id"], "auth.account_link",
                              f"user:{candidate['id']}",
                              {"provider": "apple", "email_verified": True})

    if user:
        if user.get("deletion_pending_at"):
            raise HTTPException(status_code=403, detail={
                "error": "account_deletion_pending",
            })
        admin_row = await db.admin_users.find_one({"user_id": user["id"]})
        role = admin_row["role"] if admin_row else "user"
        session_row = await session_store.create_session(
            user_id=user["id"], role=role,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        from domains.auth.google_service import _set_session_cookies, _build_bearer_body
        _set_session_cookies(response, session_row, role)
        await audit.write(user["id"], "auth.apple_login",
                          f"session:{session_row['session_id']}",
                          {"provider": "apple", "role": role,
                           "is_private_email": is_private_email})
        return {
            "status": "logged_in",
            **_build_bearer_body(user["id"]),
            "user": {
                "id": user["id"], "email": user["email"],
                "name": user["name"], "role": role,
                "passport_activated": user.get("passport_activated", False),
                "created_at": user["created_at"],
            },
        }

    # 3) New user (or private-relay-that-can't-auto-link). Create pending signup.
    pending_id = str(uuid.uuid4())
    now = utc_now()
    display_email = email or f"apple-user-{apple_sub[:12]}@no-email.apple"
    display_name = name or (email.split("@")[0] if email else f"apple-user-{apple_sub[:8]}")
    await db.pending_apple_signups.insert_one({
        "id": pending_id,
        "provider": "apple",
        "provider_user_id": apple_sub,
        "email": display_email,
        "name": display_name,
        "is_private_email": is_private_email,
        "email_verified": email_verified,
        "created_at": now,
        "expires_at": now + timedelta(minutes=PENDING_TTL_MINUTES),
    })
    await audit.write(display_email, "auth.apple_pending_signup",
                      f"pending:{pending_id}",
                      {"provider": "apple", "is_private_email": is_private_email})
    return {
        "status": "pending_consent",
        "pending_signup_id": pending_id,
        "email": display_email,
        "name": display_name,
        "is_private_email": is_private_email,
        "consent_scopes": list(SCOPE_KEYS),
        "required_scopes": list(REQUIRED_SCOPES),
        "expires_at": (now + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat(),
    }


async def complete_apple_signup(*, pending_signup_id: str, consents: dict[str, bool],
                                 policy_text_version: str, request: Request,
                                 response: Response) -> dict[str, Any]:
    db = get_db()
    pending = await db.pending_apple_signups.find_one({"id": pending_signup_id})
    if not pending:
        raise HTTPException(status_code=404, detail={
            "error": "pending_signup_not_found",
        })
    exp = pending.get("expires_at")
    if exp is not None:
        exp_naive = exp.replace(tzinfo=None) if hasattr(exp, "replace") and getattr(exp, "tzinfo", None) else exp
        now_naive = utc_now().replace(tzinfo=None)
        if exp_naive < now_naive:
            raise HTTPException(status_code=410, detail={"error": "pending_signup_expired"})

    for scope in REQUIRED_SCOPES:
        if not consents.get(scope):
            raise HTTPException(status_code=400, detail={
                "error": "required_consent_missing", "scope": scope,
            })

    email = pending["email"]

    # Race: existing account with same non-relay email → link into it.
    if not pending.get("is_private_email"):
        existing = await user_repo.by_email(email)
        if existing:
            user_id = existing["id"]
        else:
            user_id = str(uuid.uuid4())
            await user_repo.create({
                "id": user_id, "email": email, "password_hash": "",
                "name": pending["name"], "passport_activated": False,
                "created_at": utc_now(),
            })
            await audit.write(user_id, "auth.apple_signup", f"user:{user_id}",
                              {"email": email, "provider": "apple"})
    else:
        # Private-relay: always create a NEW distinct account.
        user_id = str(uuid.uuid4())
        await user_repo.create({
            "id": user_id, "email": email, "password_hash": "",
            "name": pending["name"], "passport_activated": False,
            "created_at": utc_now(),
        })
        await audit.write(user_id, "auth.apple_signup", f"user:{user_id}",
                          {"email": email, "provider": "apple",
                           "is_private_email": True})

    # Persist link (idempotent).
    await db.linked_auth_identities.update_one(
        {"provider": "apple", "provider_user_id": pending["provider_user_id"]},
        {"$set": {
            "provider": "apple",
            "provider_user_id": pending["provider_user_id"],
            "email": email,
            "user_id": user_id,
            "linked_at": utc_now(),
            "is_private_email": pending.get("is_private_email", False),
        }, "$setOnInsert": {"id": str(uuid.uuid4())}},
        upsert=True,
    )

    # Consent ledger.
    for scope, granted in consents.items():
        if scope not in SCOPE_KEYS:
            continue
        await consent_svc.record(
            user_id=user_id, scope=scope, granted=bool(granted),
            policy_text_version=policy_text_version, actor=user_id,
            source="apple_signup",
        )

    await db.pending_apple_signups.delete_one({"id": pending_signup_id})

    admin_row = await db.admin_users.find_one({"user_id": user_id})
    role = admin_row["role"] if admin_row else "user"
    session_row = await session_store.create_session(
        user_id=user_id, role=role,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    from domains.auth.google_service import _set_session_cookies, _build_bearer_body
    _set_session_cookies(response, session_row, role)
    await audit.write(user_id, "auth.session_created",
                      f"session:{session_row['session_id']}",
                      {"via": "apple_signup", "role": role,
                       "is_private_email": pending.get("is_private_email", False)})
    return {
        "status": "signed_up",
        **_build_bearer_body(user_id),
        "user": {
            "id": user_id, "email": email, "name": pending["name"],
            "role": role, "passport_activated": False,
        },
    }

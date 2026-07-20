import uuid
from fastapi import HTTPException, Request, Response, status
from core.config import settings
from core.security import hash_password, verify_password, create_access_token
from core.time_utils import utc_now
from core.policy import SCOPE_KEYS, REQUIRED_SCOPES
from core import sessions as session_store
from services import login_throttle
from domains.auth import repository as user_repo
from domains.auth.models import SignupRequest, LoginRequest
from domains.audit import service as audit
from domains.consent import service as consent_svc


def _set_session_cookies(response: Response, session_row: dict, role: str) -> None:
    """Set the httpOnly session cookie + the JS-readable CSRF cookie.
    SameSite=Strict for admin/support sessions, Lax for user sessions."""
    kw = session_store.cookie_kwargs_for_role(role)
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session_row["session_id"],
        **kw,
    )
    # CSRF cookie: JS-readable (httponly=False) so axios can echo it in the
    # X-CSRF-Token header. Double-submit is the protection, not secrecy of the
    # cookie itself.
    csrf_kw = {**kw, "httponly": False}
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=session_row["csrf_token"],
        **csrf_kw,
    )


def _clear_session_cookies(response: Response) -> None:
    for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
        response.delete_cookie(name, path="/")


def _maybe_bearer_body(user_id: str) -> dict:
    """Only expose an access_token in the response body when the CI test issuer
    flag is on. Under prod semantics this is an empty dict — clients ONLY
    receive cookies."""
    if not settings.CI_TEST_ISSUER_ENABLED:
        return {}
    return {"access_token": create_access_token(user_id), "token_type": "bearer"}


async def signup(req: SignupRequest, request: Request, response: Response) -> dict:
    email = req.email.lower()
    # SEC-P3(a) — throttle before any DB work.
    await login_throttle.check_and_record_attempt(request, "signup", email)
    if await user_repo.by_email(email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_already_registered")

    consents_map = req.consents.model_dump()
    # Enforce required scopes at signup
    for scope in REQUIRED_SCOPES:
        if not consents_map.get(scope):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "required_consent_missing", "scope": scope},
            )

    user_id = str(uuid.uuid4())
    now = utc_now()
    doc = {
        "id": user_id,
        "email": email,
        "password_hash": hash_password(req.password),
        "name": req.name.strip(),
        "passport_activated": False,
        "created_at": now,
    }
    await user_repo.create(doc)
    await audit.write(user_id, "user.signup", f"user:{user_id}", {"email": email})

    # Record consent rows for every scope the client sent (granted or not)
    for scope, granted in consents_map.items():
        if scope not in SCOPE_KEYS:
            continue
        await consent_svc.record(
            user_id=user_id,
            scope=scope,
            granted=bool(granted),
            policy_text_version=req.policy_text_version,
            actor=user_id,
            source="signup",
        )

    session_row = await session_store.create_session(
        user_id=user_id,
        role="user",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(response, session_row, "user")
    await audit.write(user_id, "auth.session_created",
                       f"session:{session_row['session_id']}",
                       {"via": "signup", "role": "user"})

    return {
        **_maybe_bearer_body(user_id),
        "user": {
            "id": user_id,
            "email": email,
            "name": doc["name"],
            "role": "user",
            "passport_activated": False,
            "created_at": now,
        },
    }


async def login(req: LoginRequest, request: Request, response: Response) -> dict:
    from core.db import get_db
    email = req.email.lower()
    # SEC-P3(a) — throttle before crypto verify so brute-forcers get counted
    # on every attempt regardless of whether the email exists.
    await login_throttle.check_and_record_attempt(request, "login", email)
    user = await user_repo.by_email(email)
    if not user or not verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    # Phase 6 — soft-delete gate.
    if user.get("deletion_pending_at"):
        raise HTTPException(status_code=403, detail={
            "error": "account_deletion_pending",
            "scheduled_for": (user.get("deletion_scheduled_for") or "").isoformat()
                if hasattr(user.get("deletion_scheduled_for"), "isoformat")
                else user.get("deletion_scheduled_for"),
            "message": "This account is pending deletion. Contact support to restore before the window closes.",
        })
    admin_row = await get_db().admin_users.find_one({"user_id": user["id"]})
    role = admin_row["role"] if admin_row else "user"

    # Rotate = fresh session id on every login (anti-fixation).
    session_row = await session_store.create_session(
        user_id=user["id"],
        role=role,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(response, session_row, role)
    # Successful login → clear the throttle bucket so a legit user's earlier
    # typos don't linger against them.
    await login_throttle.clear_bucket(request, "login", email)
    await audit.write(user["id"], "auth.session_created",
                       f"session:{session_row['session_id']}",
                       {"via": "login", "role": role})

    return {
        **_maybe_bearer_body(user["id"]),
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": role,
            "passport_activated": user.get("passport_activated", False),
            "created_at": user["created_at"],
        },
    }


async def logout(user: dict, response: Response) -> dict:
    sid = user.get("_session_id")
    if sid:
        await session_store.revoke_session(sid)
        await audit.write(user["id"], "auth.session_revoked", f"session:{sid}", {"via": "logout"})
    _clear_session_cookies(response)
    return {"ok": True}

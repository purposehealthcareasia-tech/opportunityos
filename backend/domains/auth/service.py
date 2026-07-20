import uuid
from fastapi import HTTPException, status
from core.security import hash_password, verify_password, create_access_token
from core.time_utils import utc_now
from core.policy import SCOPE_KEYS, REQUIRED_SCOPES
from domains.auth import repository as user_repo
from domains.auth.models import SignupRequest, LoginRequest
from domains.audit import service as audit
from domains.consent import service as consent_svc


async def signup(req: SignupRequest) -> dict:
    email = req.email.lower()
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

    token = create_access_token(user_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "name": doc["name"],
            "role": "user",
            "passport_activated": False,
            "created_at": now,
        },
    }


async def login(req: LoginRequest) -> dict:
    from core.db import get_db
    user = await user_repo.by_email(req.email.lower())
    if not user or not verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    # Phase 6 — soft-delete gate. deletion_pending accounts can log in ONLY via the
    # restore path; the token they receive is scoped by the /privacy/account/restore route.
    # For v0.1 we hard-block login and expose the restore instruction in the 403 detail.
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
    token = create_access_token(user["id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": role,
            "passport_activated": user.get("passport_activated", False),
            "created_at": user["created_at"],
        },
    }

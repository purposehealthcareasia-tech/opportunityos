"""Phone-OTP login (Twilio Verify) — sign-in for users who have already
attached a phone to their account.

Truthful CONFIGURATION_REQUIRED behavior: when TWILIO_* env vars are absent,
`/otp/start` and `/otp/verify` both return **503 `otp_not_configured`** so
the frontend can render an honest disabled state instead of a broken button.
The provider adapter (integrations/sms/twilio_provider.py) already reports
the same status truthfully in the Admin Integrations dashboard.

Rate-limited via `services.login_throttle.check_and_record_attempt` on both
phone number AND IP (30 sends per 5 min per phone; 10 verify attempts per
5 min per phone).

Sensitive material NEVER exposed:
  - Twilio Account SID / Auth Token / Verify Service SID: only NAMES appear
    in status responses.
  - OTP codes: not stored server-side (Twilio owns the verification
    lifecycle); only the request's dedup key + audit rows are persisted.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import HTTPException, Request, Response

from core.db import get_db
from core.time_utils import utc_now
from core import sessions as session_store
from services import login_throttle
from domains.auth import repository as user_repo
from domains.audit import service as audit
from integrations import registry


log = logging.getLogger("oppos.auth.otp")


_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")


def _normalize_phone(raw: str) -> str:
    """Return an E.164 phone (+ followed by 2–15 digits) or raise 400."""
    if not raw or not isinstance(raw, str):
        raise HTTPException(status_code=400, detail={"error": "phone_invalid"})
    # Strip spaces / dashes / parens, keep leading +.
    normalized = re.sub(r"[\s()\-]", "", raw.strip())
    if not _E164_RE.match(normalized):
        raise HTTPException(status_code=400, detail={
            "error": "phone_invalid",
            "message": "Phone must be in E.164 format, e.g. +14155552671.",
        })
    return normalized


def _twilio() -> Any:
    prov = registry.get("twilio")
    if not prov:
        return None
    v = prov.validate_configuration()
    if not v.ok:
        return None
    return prov


def _require_twilio():
    p = _twilio()
    if not p:
        raise HTTPException(status_code=503, detail={
            "error": "otp_not_configured",
            "message": "Phone one-time code sign-in is not yet configured on this server.",
        })
    return p


async def ensure_indexes() -> None:
    db = get_db()
    # Reverse lookup by phone for login.
    await db.users.create_index("phone", sparse=True)


async def start_otp(*, phone: str, request: Request) -> dict[str, Any]:
    provider = _require_twilio()
    normalized = _normalize_phone(phone)
    # Rate-limit: 30 sends per bucket window per phone AND per IP.
    await login_throttle.check_and_record_attempt(request, "otp_start", normalized)

    try:
        result = await provider.start_verify(to=normalized, channel="sms")
    except Exception as e:
        # ProviderError → truthful upstream failure. Never expose SID/token.
        log.warning("Twilio start_verify failed: %s", str(e)[:200])
        raise HTTPException(status_code=502, detail={
            "error": "otp_send_upstream_failed",
            "message": "Could not send OTP right now — please try again shortly.",
        })
    await audit.write("system:otp", "auth.otp_sent",
                      f"phone:{normalized[-4:]}",
                      {"channel": "sms", "sid": result.get("sid")})
    return {"ok": True, "channel": "sms", "phone_tail": normalized[-4:]}


async def verify_otp(*, phone: str, code: str, request: Request,
                     response: Response) -> dict[str, Any]:
    provider = _require_twilio()
    normalized = _normalize_phone(phone)

    if not code or len(code) < 4 or len(code) > 10 or not code.isdigit():
        raise HTTPException(status_code=400, detail={"error": "otp_code_invalid"})

    # Rate-limit verify separately (10 tries per bucket window).
    await login_throttle.check_and_record_attempt(request, "otp_verify", normalized)

    try:
        result = await provider.check_verify(to=normalized, code=code)
    except Exception as e:
        log.warning("Twilio check_verify failed: %s", str(e)[:200])
        raise HTTPException(status_code=502, detail={
            "error": "otp_verify_upstream_failed",
        })
    if not result.get("approved"):
        await audit.write("system:otp", "auth.otp_failed",
                          f"phone:{normalized[-4:]}",
                          {"status": result.get("status")})
        raise HTTPException(status_code=401, detail={
            "error": "otp_code_incorrect",
            "message": "Code is incorrect or expired. Request a new one and try again.",
        })

    # OTP approved → find the user by phone. Login-only flow (no signup).
    db = get_db()
    user = await db.users.find_one({"phone": normalized})
    if not user:
        # Honest error — not silently upserted (consent-first invariant).
        raise HTTPException(status_code=404, detail={
            "error": "no_account_for_phone",
            "message": "No account is attached to this phone. Sign up with email, "
                        "Google, or Apple first, then attach your phone from Settings.",
        })
    if user.get("deletion_pending_at"):
        raise HTTPException(status_code=403, detail={"error": "account_deletion_pending"})

    admin_row = await db.admin_users.find_one({"user_id": user["id"]})
    role = admin_row["role"] if admin_row else "user"
    session_row = await session_store.create_session(
        user_id=user["id"], role=role,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    from domains.auth.google_service import _set_session_cookies, _build_bearer_body
    _set_session_cookies(response, session_row, role)
    await login_throttle.clear_bucket(request, "otp_verify", normalized)
    await login_throttle.clear_bucket(request, "otp_start", normalized)
    await audit.write(user["id"], "auth.otp_login",
                      f"session:{session_row['session_id']}",
                      {"role": role, "phone_tail": normalized[-4:]})
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


async def attach_phone_to_user(*, user_id: str, phone: str, code: str,
                               request: Request) -> dict[str, Any]:
    """Attach a verified phone to an existing (already-authenticated) user."""
    provider = _require_twilio()
    normalized = _normalize_phone(phone)
    if not code or not code.isdigit():
        raise HTTPException(status_code=400, detail={"error": "otp_code_invalid"})
    await login_throttle.check_and_record_attempt(request, "otp_attach", normalized)

    try:
        result = await provider.check_verify(to=normalized, code=code)
    except Exception:
        raise HTTPException(status_code=502, detail={"error": "otp_verify_upstream_failed"})
    if not result.get("approved"):
        raise HTTPException(status_code=401, detail={"error": "otp_code_incorrect"})

    db = get_db()
    # Refuse to attach a phone already on another account.
    existing = await db.users.find_one({"phone": normalized, "id": {"$ne": user_id}})
    if existing:
        raise HTTPException(status_code=409, detail={"error": "phone_already_attached_elsewhere"})
    await db.users.update_one({"id": user_id}, {"$set": {"phone": normalized}})
    await audit.write(user_id, "auth.phone_attached", f"user:{user_id}",
                      {"phone_tail": normalized[-4:]})
    return {"ok": True, "phone_tail": normalized[-4:]}

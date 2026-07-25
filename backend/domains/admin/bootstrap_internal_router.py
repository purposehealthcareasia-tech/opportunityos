"""One-time production admin bootstrap endpoint (A4 · Publish #3).

Grants the founder account both `admin` role and the top ("max") subscription
plan in a single audited operation. Self-disabling: once ANY admin_users row
exists, all subsequent calls return 409 — so the endpoint can safely live in
production after the initial bootstrap without becoming a lateral-movement
tool.

Gate:
  * INTERNAL_SERVICE_TOKEN via `X-Service-Token` header — same semantics as
    `/api/internal/fixture/rebase`: missing→401, wrong→403, unset→503.
  * If any admin_users row already exists → 409 self-disable.

Effect (single atomic op, audited):
  1. Grants `role=admin` to the user whose email is exactly
     `swissarjun77@gmail.com` (upsert into `admin_users`).
  2. Sets that same user's subscription to the top plan `max` via
     internal `subscriptions.set_plan(actor="system:founder_bootstrap")`.
  3. Writes two audit_logs rows: `admin.role_granted` +
     `admin.plan_granted`, both with actor `system:founder_bootstrap`.

The endpoint never echoes the service token, the founder's email hash, or
any password material.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, status

from core.config import settings
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit
from domains.subscriptions import service as subs_svc
from services import plans as plans_svc


# Fixed constants — this is a one-time bootstrap tool, not a general-purpose
# grant. Founder email is baked in; there is no user-supplied identity path
# that could accidentally promote a different account.
FOUNDER_EMAIL = "swissarjun77@gmail.com"
FOUNDER_TOP_PLAN = "max"
BOOTSTRAP_ACTOR = "system:founder_bootstrap"


router = APIRouter(prefix="/api/internal/admin", tags=["internal:admin"])


async def _check_service_token(
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
):
    expected = settings.INTERNAL_SERVICE_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "internal_service_token_not_configured"},
        )
    if not x_service_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "service_token_missing"},
        )
    if x_service_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "service_token_invalid"},
        )
    return True


@router.post("/bootstrap-founder", status_code=200)
async def bootstrap_founder(_ok: bool = Depends(_check_service_token)):
    """Grants role=admin + max plan to the founder account. One-shot,
    self-disabling, audited. See module docstring for full contract."""
    db = get_db()

    # Self-disable — if any admin_users row exists, refuse.
    existing_admin_count = await db.admin_users.count_documents({})
    if existing_admin_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "bootstrap_already_completed",
                "admin_users_count": existing_admin_count,
            },
        )

    # Locate founder user (must exist — signup blocked from bootstrap path)
    user = await db.users.find_one(
        {"email": FOUNDER_EMAIL},
        {"_id": 0, "id": 1, "email": 1},
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "founder_user_not_found"},
        )

    # Plan slug sanity — refuse if the constant drifts out of the enum.
    if FOUNDER_TOP_PLAN not in plans_svc.PLANS:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "top_plan_slug_invalid",
                "allowed": sorted(plans_svc.PLANS.keys()),
            },
        )

    # 1. Grant admin role
    await db.admin_users.update_one(
        {"user_id": user["id"]},
        {"$set": {"role": "admin"}, "$setOnInsert": {"user_id": user["id"], "ts": utc_now()}},
        upsert=True,
    )
    await audit.write(
        BOOTSTRAP_ACTOR,
        "admin.role_granted",
        f"user:{user['id']}",
        {"role": "admin", "channel": "bootstrap_endpoint"},
    )

    # 2. Set top plan
    sub = await subs_svc.set_plan(user["id"], FOUNDER_TOP_PLAN, actor=BOOTSTRAP_ACTOR)
    await audit.write(
        BOOTSTRAP_ACTOR,
        "admin.plan_granted",
        f"user:{user['id']}",
        {
            "plan": FOUNDER_TOP_PLAN,
            "channel": "bootstrap_endpoint",
            "subscription_id": sub.get("id"),
        },
    )

    return {
        "ok": True,
        "user_id": user["id"],
        "role_granted": "admin",
        "plan_granted": FOUNDER_TOP_PLAN,
        "subscription_id": sub.get("id"),
        "note": "This endpoint is now self-disabled. Any further POST returns 409.",
    }

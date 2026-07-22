"""Notification HTTP endpoints.

Everything (except `/vapid-public-key`, which is safe to expose) is
authenticated + audited. Subscribe + test-send are rate-limited via the
existing `services.login_throttle` primitives (per-identifier + per-IP).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request

from core.deps import get_current_user
from domains.audit import service as audit
from domains.notifications import NOTIFICATION_CATEGORIES, service as svc
from domains.notifications.models import (
    PreferencesUpdate,
    SubscribeRequest,
    UnsubscribeRequest,
)
from services.login_throttle import check_and_record_attempt


router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Public — the browser needs this key at subscription time.

    Returns `{ok: false, ...}` (200) when VAPID is not configured so the UI
    can render an honest 'not yet available' state without treating it as
    an error. Never returns the private key.
    """
    pub = os.environ.get("VAPID_PUBLIC_KEY", "")
    sub = os.environ.get("VAPID_SUBJECT", "")
    if not (pub and sub and sub.startswith("mailto:")):
        return {"ok": False, "reason": "configuration_required",
                "public_key": None}
    return {"ok": True, "public_key": pub, "supported_categories": list(NOTIFICATION_CATEGORIES.keys())}


@router.get("/preferences")
async def read_preferences(user: dict = Depends(get_current_user)):
    prefs = await svc.get_preferences(user["id"])
    return {"categories": prefs, "catalog": NOTIFICATION_CATEGORIES}


@router.put("/preferences")
async def update_preferences(
    payload: PreferencesUpdate,
    user: dict = Depends(get_current_user),
):
    updates = payload.as_dict()
    prefs = await svc.set_preferences(user["id"], updates, actor=user["id"])
    return {"categories": prefs, "catalog": NOTIFICATION_CATEGORIES}


@router.get("/subscriptions")
async def list_my_subscriptions(user: dict = Depends(get_current_user)):
    return {"subscriptions": await svc.list_subscriptions(user["id"])}


@router.post("/subscribe", status_code=201)
async def subscribe(
    payload: SubscribeRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    # Rate limit: per-user AND per-IP (raises 429 automatically).
    await check_and_record_attempt(
        request, route=svc.RATE_ROUTE_SUBSCRIBE, identifier=user["id"],
    )
    try:
        row = await svc.register_subscription(
            user_id=user["id"],
            subscription=payload.subscription.model_dump(),
            user_agent=payload.user_agent,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    # Never return the raw p256dh/auth to the client.
    row.pop("keys", None)
    return row


@router.post("/unsubscribe", status_code=200)
async def unsubscribe(
    payload: UnsubscribeRequest,
    user: dict = Depends(get_current_user),
):
    ok = await svc.revoke_subscription(user_id=user["id"], endpoint=payload.endpoint)
    if not ok:
        # Not the caller's subscription (ownership check failed) OR already
        # inactive — same 404 to avoid leaking the distinction.
        raise HTTPException(status_code=404, detail={"error": "subscription_not_found"})
    return {"ok": True}


@router.post("/test", status_code=200)
async def send_test(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Dispatch a generic test push to every active subscription for the
    authenticated user. Payload minimalism enforced by the service.
    """
    await check_and_record_attempt(
        request, route=svc.RATE_ROUTE_TEST_SEND, identifier=user["id"],
    )
    summary = await svc.dispatch(
        user["id"], category="application_updates",
        data={"url": "/notifications"},
        dedup_key=None,
    )
    await audit.write(user["id"], "notifications.test_send",
                      f"user:{user['id']}",
                      {"summary": {k: v for k, v in summary.items()
                                    if k in ("sent", "failed", "skipped", "pruned", "category")}})
    return summary

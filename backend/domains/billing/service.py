"""Phase 6 Billing — Stripe test-mode via emergentintegrations Flow B.

Deviation recorded in PRD: claimable-sandbox Flow A returned country_not_supported
(sandbox account country=IN). We use Flow B with the pre-injected STRIPE_API_KEY
(`sk_test_emergent`) via the `emergentintegrations.payments.stripe.checkout` helper.

Endpoints (all under `/api/v1/billing`):
  GET  /catalog           — list plans + prices (server-defined; NEVER trust client)
  POST /checkout          — {lookup_key, origin_url, coupon?} → {checkout_url, session_id}
  POST /session-confirm   — {session_id} → syncs subscription state (poll-based)
  POST /cancel            — cancel-at-period-end for current user's subscription
  POST /refund            — 7-day self-serve refund for the most recent invoice
  POST /coupon/apply      — {code} → validates & records (currently only FOUNDER19)
  GET  /invoices          — list of invoices (payment_transactions) for current user

Additionally: `/api/webhook/stripe` (canonical Flow B path) for delivery-optional sync.
The primary sync mechanism is polling `POST /session-confirm` from the return page.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout, CheckoutSessionRequest,
)

from core.db import get_db
from core.deps import get_current_user
from core.time_utils import utc_now
from domains.audit import service as audit
from domains.subscriptions import service as subs_svc


router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/api/webhook", tags=["billing:webhook"])


# ---------- Server-defined catalog. Amounts float. NEVER trust the client. ----------
PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "plus_monthly": {"plan": "plus", "amount": 19.0, "currency": "usd", "label": "Plus (monthly)"},
    "pro_monthly":  {"plan": "pro",  "amount": 49.0, "currency": "usd", "label": "Pro (monthly)"},
    "max_monthly":  {"plan": "max",  "amount": 99.0, "currency": "usd", "label": "Max (monthly)"},
}

# Founder coupon — spec §A.3
FOUNDER_COUPON = {
    "code": "FOUNDER19",
    "grants_plan": "plus",
    "amount_override": 19.0,
    "grandfathered_12mo": True,
}


class CheckoutBody(BaseModel):
    lookup_key: str = Field(..., description="One of PLAN_CATALOG keys.")
    origin_url: str = Field(..., description="Frontend origin — used for success/cancel URLs.")
    coupon: str | None = None


class SessionConfirmBody(BaseModel):
    session_id: str


class CouponBody(BaseModel):
    code: str


def _stripe_client(request: Request) -> StripeCheckout:
    api_key = os.environ.get("STRIPE_API_KEY", "sk_test_emergent")
    host_url = str(request.base_url)  # e.g. https://lynk-preview-2.preview.emergentagent.com/
    webhook_url = f"{host_url.rstrip('/')}/api/webhook/stripe"
    return StripeCheckout(api_key=api_key, webhook_url=webhook_url)


# ---------- Catalog + coupon ----------

@router.get("/catalog")
async def get_catalog():
    """Full catalog + verbatim meter definitions (spec §A.3)."""
    return {
        "plans": PLAN_CATALOG,
        "meter_definitions_verbatim": {
            "jobs_processed": "discovered+verified+scored for you",
            "applications_prepared": "tailored packets awaiting your approval",
            "apps_submitted": "sent with receipt",
        },
        "caps_by_plan": {
            "free": {"jobs_hourly": 25,  "prepared_monthly": 5,   "submits_daily": 3},
            "plus": {"jobs_hourly": 100, "prepared_monthly": 60,  "submits_daily": 15},
            "pro":  {"jobs_hourly": 250, "prepared_monthly": 200, "submits_daily": 25},
            "max":  {"jobs_hourly": 500, "prepared_monthly": 400, "submits_daily": 40},  # 400 SOFT
        },
        "founder_coupon": {"code": FOUNDER_COUPON["code"], "grants": "plus @ $19/mo + grandfathered_12mo"},
    }


@router.post("/coupon/apply")
async def validate_coupon(body: CouponBody, user: dict = Depends(get_current_user)):
    if body.code.strip().upper() == FOUNDER_COUPON["code"]:
        return {
            "valid": True,
            "grants_plan": FOUNDER_COUPON["grants_plan"],
            "amount_override": FOUNDER_COUPON["amount_override"],
            "grandfathered_12mo": True,
            "message": "$19/mo forever on the Plus plan.",
        }
    return {"valid": False, "message": "Unknown coupon code."}


# ---------- Checkout ----------

@router.post("/checkout")
async def create_checkout(body: CheckoutBody, request: Request, user: dict = Depends(get_current_user)):
    if body.lookup_key not in PLAN_CATALOG:
        raise HTTPException(status_code=400, detail={"error": "unknown_lookup_key"})
    entry = PLAN_CATALOG[body.lookup_key]
    amount = float(entry["amount"])
    metadata: dict[str, str] = {
        "user_id": str(user["id"]),
        "lookup_key": body.lookup_key,
        "target_plan": entry["plan"],
    }
    # Coupon handling — server-side only.
    if body.coupon and body.coupon.strip().upper() == FOUNDER_COUPON["code"]:
        amount = float(FOUNDER_COUPON["amount_override"])
        metadata["coupon"] = FOUNDER_COUPON["code"]
        metadata["grandfathered_12mo"] = "true"
    stripe = _stripe_client(request)
    origin = body.origin_url.rstrip("/")
    success_url = f"{origin}/billing?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/billing?cancel=1"
    req = CheckoutSessionRequest(
        amount=amount, currency=str(entry["currency"]),
        success_url=success_url, cancel_url=cancel_url, metadata=metadata,
    )
    try:
        session = await stripe.create_checkout_session(req)
    except Exception as e:  # noqa: BLE001 — surface message to client
        raise HTTPException(status_code=502, detail={"error": "stripe_error", "message": str(e)[:180]})

    db = get_db()
    now = utc_now()
    await db.payment_transactions.insert_one({
        "id": str(uuid.uuid4()),
        "session_id": session.session_id,
        "user_id": user["id"],
        "lookup_key": body.lookup_key,
        "target_plan": entry["plan"],
        "amount": amount,
        "currency": entry["currency"],
        "status": "initiated",
        "payment_status": "pending",
        "coupon": metadata.get("coupon"),
        "grandfathered_12mo": metadata.get("grandfathered_12mo") == "true",
        "created_at": now,
        "updated_at": now,
    })
    await audit.write(user["id"], "billing.checkout_created",
                      f"session:{session.session_id}",
                      {"lookup_key": body.lookup_key, "amount": amount,
                       "coupon": metadata.get("coupon")})
    return {"checkout_url": session.url, "session_id": session.session_id, "amount": amount}


@router.post("/session-confirm")
async def confirm_session(body: SessionConfirmBody, request: Request, user: dict = Depends(get_current_user)):
    """Poll-based session sync. Called by the frontend when the user returns from Stripe."""
    db = get_db()
    tx = await db.payment_transactions.find_one({"session_id": body.session_id, "user_id": user["id"]}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="session_not_found")
    if tx.get("payment_status") == "paid":
        return {"session_id": body.session_id, "payment_status": "paid",
                "status": tx.get("status"), "plan_after": tx.get("target_plan"), "already_synced": True}

    stripe = _stripe_client(request)
    try:
        status = await stripe.get_checkout_status(body.session_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "stripe_error", "message": str(e)[:180]})

    payment_status = str(status.payment_status or "").lower()
    sess_status = str(status.status or "").lower()
    if payment_status == "paid" or sess_status == "complete":
        # Idempotent — only advance if not already advanced.
        upd = await db.payment_transactions.update_one(
            {"session_id": body.session_id, "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": "paid", "updated_at": utc_now()}},
        )
        if upd.modified_count == 1:
            # Advance subscription plan.
            await subs_svc.set_plan(user["id"], tx["target_plan"], actor="system:stripe")
            # Grandfathered flag if founder coupon applied.
            if tx.get("grandfathered_12mo"):
                await db.subscriptions.update_one(
                    {"user_id": user["id"]},
                    {"$set": {"grandfathered_12mo": True,
                              "grandfathered_until": (utc_now() + timedelta(days=365))}},
                )
            await audit.write(user["id"], "billing.plan_upgraded",
                              f"session:{body.session_id}", {"plan": tx["target_plan"]})
        return {"session_id": body.session_id, "payment_status": "paid",
                "status": "completed", "plan_after": tx["target_plan"]}
    return {"session_id": body.session_id, "payment_status": payment_status or "pending",
            "status": sess_status or tx.get("status"), "plan_after": tx.get("target_plan")}


@router.post("/cancel")
async def cancel_subscription(user: dict = Depends(get_current_user)):
    """Cancel at period end (≤2 clicks — spec §A.3)."""
    db = get_db()
    sub = await db.subscriptions.find_one({"user_id": user["id"]}, {"_id": 0})
    if not sub or sub.get("plan") == "free":
        raise HTTPException(status_code=409, detail={"error": "no_paid_subscription",
                                                       "message": "You're on the free plan — nothing to cancel."})
    # v0.1: mark cancel_at_period_end locally. If the sub has a real Stripe subscription id,
    # a future Stripe API call would flip cancel_at_period_end there too.
    await db.subscriptions.update_one(
        {"user_id": user["id"]},
        {"$set": {"cancel_at_period_end": True, "cancel_scheduled_at": utc_now(),
                  "updated_at": utc_now()}},
    )
    await audit.write(user["id"], "billing.cancel_scheduled", f"user:{user['id']}", {})
    return {"cancelled_at_period_end": True,
            "message": "Cancellation scheduled. You keep Plus/Pro/Max features until the period ends."}


@router.post("/refund")
async def self_serve_refund(user: dict = Depends(get_current_user)):
    """7-day self-serve first-purchase refund on most recent invoice."""
    db = get_db()
    cutoff = utc_now() - timedelta(days=7)
    tx = await db.payment_transactions.find_one(
        {"user_id": user["id"], "payment_status": "paid",
         "created_at": {"$gte": cutoff}, "refunded_at": None},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not tx:
        raise HTTPException(status_code=409, detail={"error": "no_refundable_purchase",
                                                       "message": "No paid purchase in the last 7 days that hasn't already been refunded."})
    # Mark refunded locally. Stripe test-mode refund via SDK requires payment_intent_id which
    # the emergent helper does not surface for Flow B; we honor the policy locally and audit.
    await db.payment_transactions.update_one(
        {"id": tx["id"]},
        {"$set": {"refunded_at": utc_now(), "status": "refunded", "payment_status": "refunded",
                  "refund_reason": "self_serve_first_purchase_7d", "updated_at": utc_now()}},
    )
    await subs_svc.set_plan(user["id"], "free", actor="system:refund")
    await audit.write(user["id"], "billing.refund_self_serve", f"session:{tx['session_id']}",
                      {"amount": tx["amount"], "reason": "self_serve_first_purchase_7d"})
    return {"refunded": True, "amount": tx["amount"], "session_id": tx["session_id"]}


@router.get("/invoices")
async def list_invoices(user: dict = Depends(get_current_user)):
    cur = get_db().payment_transactions.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    return {"invoices": [t async for t in cur]}


# ---------- Webhook (Flow B path) ----------

@webhook_router.post("/stripe")
async def stripe_webhook(request: Request):
    """Optional sync path — session polling is the primary mechanism. Webhook here is a
    belt-and-suspenders channel that idempotently flips the payment_status when Stripe
    happens to deliver."""
    api_key = os.environ.get("STRIPE_API_KEY", "sk_test_emergent")
    host_url = str(request.base_url)
    webhook_url = f"{host_url.rstrip('/')}/api/webhook/stripe"
    stripe = StripeCheckout(api_key=api_key, webhook_url=webhook_url)
    body_bytes = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        evt = await stripe.handle_webhook(body_bytes, sig)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": "webhook_verify_failed", "message": str(e)[:120]})
    if not evt or not evt.session_id:
        return {"ok": True, "ignored": True}
    if (evt.payment_status or "").lower() == "paid":
        db = get_db()
        await db.payment_transactions.update_one(
            {"session_id": evt.session_id, "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": "paid", "updated_at": utc_now()}},
        )
    return {"ok": True, "event_type": evt.event_type, "event_id": evt.event_id}

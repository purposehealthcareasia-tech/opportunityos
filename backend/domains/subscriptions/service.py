"""Subscriptions — Phase 5 enforcement-lite. Full Stripe wiring lands in Phase 6.

Data model:
  { id, user_id, plan (free|plus|pro|max), state, stripe_customer_id?, stripe_subscription_id?,
    period_start, period_end, updated_at, created_at }

Only ONE non-cancelled subscription per user (unique index user_id + partial filter).
For now, `state` is always 'active' (billing lives in Phase 6). The router surface is
read-only from the user's perspective; plan changes go through admin/billing paths.
"""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends
from core.db import get_db
from core.deps import get_current_user
from core.time_utils import utc_now
from services import plans as plans_svc


router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])


async def _ensure_subscription(user_id: str, plan_slug: str = plans_svc.DEFAULT_PLAN) -> dict:
    """Return the user's current subscription. Creates a free-plan row if none exists."""
    db = get_db()
    existing = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "plan": plan_slug,
        "state": "active",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "period_start": None,
        "period_end": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    await db.subscriptions.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def set_plan(user_id: str, plan_slug: str, *, actor: str = "system") -> dict:
    """Upsert the user's plan. Only meaningful for seed / fixture rebase in Phase 5."""
    assert plan_slug in plans_svc.PLANS, f"unknown plan: {plan_slug}"
    db = get_db()
    now = utc_now()
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {"plan": plan_slug, "state": "active", "updated_at": now},
            "$setOnInsert": {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "created_at": now,
                "stripe_customer_id": None,
                "stripe_subscription_id": None,
                "period_start": None,
                "period_end": None,
            },
        },
        upsert=True,
    )
    doc = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    return doc


async def get_plan_config(user_id: str) -> plans_svc.PlanConfig:
    """Resolve the plan config for a user. Auto-provisions a free-plan row if missing."""
    sub = await _ensure_subscription(user_id)
    return plans_svc.resolve(sub.get("plan"))


@router.get("/me")
async def read_my_subscription(user: dict = Depends(get_current_user)):
    sub = await _ensure_subscription(user["id"])
    cfg = plans_svc.resolve(sub.get("plan"))
    return {
        "plan": sub.get("plan"),
        "state": sub.get("state"),
        "label": cfg.label,
        "daily_submit_cap": cfg.daily_submit_cap,
    }

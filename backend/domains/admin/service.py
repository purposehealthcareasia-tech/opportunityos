"""Phase 6 Admin console.

Role-gated (admin or support). Sealed values MASKED for both roles. Every admin READ
of a user detail writes an audit row (spec §C.1).

Endpoints (all under `/api/v1/admin`):
  GET  /users                — search + list
  GET  /users/{id}           — masked detail (writes audit row)
  GET  /subscriptions        — list all
  POST /subscriptions/{id}/refund — reason enum + note required
  GET  /manual-queue         — unresolved manual_queue_items
  POST /manual-queue/{id}/resolve — {note}
  GET  /flags                — feature flags CRUD
  POST /flags                — {name, enabled, description}
  PATCH /flags/{name}        — {enabled}
  DELETE /flags/{name}
  GET  /support-tickets      — list open/replied/closed
  POST /support-tickets/{id}/reply — {reply}
  POST /support-tickets/{id}/close
  GET  /health               — real DB counts + queue depth
  GET  /observability/events — internal analytics events (labeled STUB)
  POST /observability/test-error — emits a test error (labeled STUB)
"""
from __future__ import annotations
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from fastapi.encoders import jsonable_encoder

from core.db import get_db
from core.deps import get_current_user
from core.time_utils import utc_now
from domains.audit import service as audit


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


SEALED_MASK = "🔒 masked (sealed sensitivity)"
REFUND_REASONS = {"duplicate_charge", "customer_request", "billing_error", "goodwill", "policy_bounded_first_purchase"}


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Read access — admin AND support."""
    role = user.get("role") or "user"
    if role not in {"admin", "support"}:
        raise HTTPException(status_code=403, detail={"error": "role_required",
                                                       "message": "Admin/support role required."})
    return user


def _require_admin_only(user: dict = Depends(get_current_user)) -> dict:
    """Write access — admin ONLY. Support role is read-only everywhere except
    support-ticket reply/close (which explicitly opts back into support with
    `_require_admin`). This is enforced server-side per founder amendment 2(e)."""
    role = user.get("role") or "user"
    if role != "admin":
        raise HTTPException(status_code=403, detail={"error": "admin_required",
                                                       "message": "Only admin role may mutate this resource."})
    return user


def _mask_sealed(claim: dict) -> dict:
    """Mask value fields of any sealed claim. The claim shape stays intact so the
    UI can still show the type/label/status."""
    if (claim.get("sensitivity") or "").lower() == "sealed":
        return {**claim, "value": SEALED_MASK}
    return claim


# ---------- User management (A1) ----------

@router.get("/users")
async def list_users(q: str = "", staff: dict = Depends(_require_admin)):
    db = get_db()
    filt: dict = {}
    if q.strip():
        filt = {"$or": [
            {"email": {"$regex": q, "$options": "i"}},
            {"id":    {"$regex": q, "$options": "i"}},
        ]}
    cur = db.users.find(filt, {"_id": 0, "id": 1, "email": 1, "role": 1,
                                 "created_at": 1, "deletion_pending_at": 1, "deletion_scheduled_for": 1}).limit(50)
    users = [u async for u in cur]
    return {"users": jsonable_encoder(users), "count": len(users)}


@router.get("/users/{user_id}")
async def get_user_detail(user_id: str, staff: dict = Depends(_require_admin)):
    db = get_db()
    row = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")
    # Sealed masking on claims.
    claims_raw = [c async for c in db.claims.find({"user_id": user_id}, {"_id": 0})]
    claims = [_mask_sealed(c) for c in claims_raw]
    sub = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    apps_count = await db.applications.count_documents({"user_id": user_id})
    receipts_count = await db.submission_receipts.count_documents({"user_id": user_id})
    await audit.write(staff["id"], "admin.user_detail_view", f"user:{user_id}",
                      {"staff_role": staff.get("role")})
    return jsonable_encoder({
        "user": row,
        "claims": claims,
        "subscription": sub,
        "counts": {"applications": apps_count, "receipts": receipts_count},
    })


# ---------- Subscriptions + refund (A6) ----------

@router.get("/subscriptions")
async def list_subscriptions(staff: dict = Depends(_require_admin)):
    subs = [s async for s in get_db().subscriptions.find({}, {"_id": 0}).limit(100)]
    return {"subscriptions": jsonable_encoder(subs), "count": len(subs)}


class RefundBody(BaseModel):
    reason: str = Field(..., description="Must be one of REFUND_REASONS.")
    note: str = Field(default="", max_length=1000)


@router.post("/subscriptions/{sub_id}/refund")
async def admin_refund(sub_id: str, body: RefundBody, staff: dict = Depends(_require_admin_only)):
    if body.reason not in REFUND_REASONS:
        raise HTTPException(status_code=400, detail={"error": "invalid_reason",
                                                       "allowed": sorted(REFUND_REASONS)})
    db = get_db()
    sub = await db.subscriptions.find_one({"id": sub_id}, {"_id": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="subscription_not_found")
    # Refund the most recent paid tx for that user (if any).
    tx = await db.payment_transactions.find_one(
        {"user_id": sub["user_id"], "payment_status": "paid", "refunded_at": None},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if tx:
        await db.payment_transactions.update_one(
            {"id": tx["id"]},
            {"$set": {"refunded_at": utc_now(), "status": "refunded", "payment_status": "refunded",
                      "refund_reason": body.reason, "refund_note": body.note,
                      "refunded_by": staff["id"], "updated_at": utc_now()}},
        )
    await audit.write(staff["id"], "admin.refund_issued", f"subscription:{sub_id}",
                      {"reason": body.reason, "note": body.note, "tx_id": tx.get("id") if tx else None})
    return {"refunded": True, "reason": body.reason, "tx_id": (tx or {}).get("id")}


# ---------- Manual queue (A4) ----------

@router.get("/manual-queue")
async def admin_manual_queue(staff: dict = Depends(_require_admin)):
    items = [i async for i in get_db().manual_queue_items.find({"state": "queued"}, {"_id": 0})]
    return {"items": jsonable_encoder(items)}


class ResolveBody(BaseModel):
    note: str = Field(default="", max_length=1000)


@router.post("/manual-queue/{item_id}/resolve")
async def resolve_manual_item(item_id: str, body: ResolveBody, staff: dict = Depends(_require_admin_only)):
    db = get_db()
    item = await db.manual_queue_items.find_one_and_update(
        {"id": item_id, "state": "queued"},
        {"$set": {"state": "resolved", "resolved_at": utc_now(),
                  "resolved_by": staff["id"], "resolution_note": body.note}},
        projection={"_id": 0}, return_document=True,
    )
    if not item:
        raise HTTPException(status_code=404, detail="item_not_found_or_not_queued")
    await audit.write(staff["id"], "admin.manual_queue_resolved",
                      f"item:{item_id}", {"note": body.note})
    return jsonable_encoder(item)


# ---------- Feature flags (A8) ----------

class FlagBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    enabled: bool = True
    description: str = ""


class FlagToggle(BaseModel):
    enabled: bool


@router.get("/flags")
async def list_flags(staff: dict = Depends(_require_admin)):
    flags = [f async for f in get_db().feature_flags.find({}, {"_id": 0})]
    return {"flags": jsonable_encoder(flags)}


@router.post("/flags")
async def create_flag(body: FlagBody, staff: dict = Depends(_require_admin_only)):
    db = get_db()
    now = utc_now()
    doc = {"name": body.name, "enabled": body.enabled, "description": body.description,
           "created_at": now, "updated_at": now, "created_by": staff["id"]}
    await db.feature_flags.update_one({"name": body.name},
                                      {"$set": doc}, upsert=True)
    await audit.write(staff["id"], "admin.flag_upsert", f"flag:{body.name}",
                      {"enabled": body.enabled})
    return doc


@router.patch("/flags/{name}")
async def toggle_flag(name: str, body: FlagToggle, staff: dict = Depends(_require_admin_only)):
    db = get_db()
    row = await db.feature_flags.find_one_and_update(
        {"name": name},
        {"$set": {"enabled": body.enabled, "updated_at": utc_now(), "updated_by": staff["id"]}},
        projection={"_id": 0}, return_document=True,
    )
    if not row:
        raise HTTPException(status_code=404, detail="flag_not_found")
    await audit.write(staff["id"], "admin.flag_toggled", f"flag:{name}",
                      {"enabled": body.enabled})
    return row


@router.delete("/flags/{name}")
async def delete_flag(name: str, staff: dict = Depends(_require_admin_only)):
    r = await get_db().feature_flags.delete_one({"name": name})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="flag_not_found")
    await audit.write(staff["id"], "admin.flag_deleted", f"flag:{name}", {})
    return {"deleted": True}


# ---------- Support tickets (A10) ----------

@router.get("/support-tickets")
async def list_tickets(staff: dict = Depends(_require_admin)):
    tix = [t async for t in get_db().support_tickets.find({}, {"_id": 0}).sort("created_at", -1)]
    return {"tickets": jsonable_encoder(tix)}


class ReplyBody(BaseModel):
    reply: str = Field(..., min_length=1, max_length=5000)


@router.post("/support-tickets/{ticket_id}/reply")
async def reply_ticket(ticket_id: str, body: ReplyBody, staff: dict = Depends(_require_admin)):
    db = get_db()
    now = utc_now()
    ticket = await db.support_tickets.find_one_and_update(
        {"id": ticket_id},
        {"$set": {"status": "replied", "updated_at": now, "last_reply_by": staff["id"]},
         "$push": {"replies": {"by": staff["id"], "text": body.reply, "ts": now}}},
        projection={"_id": 0}, return_document=True,
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    await audit.write(staff["id"], "admin.ticket_replied", f"ticket:{ticket_id}", {})
    # NOTE: actual email send is a labeled stub per spec §C.5 — nothing goes out on the wire.
    return jsonable_encoder(ticket)


@router.post("/support-tickets/{ticket_id}/close")
async def close_ticket(ticket_id: str, staff: dict = Depends(_require_admin)):
    db = get_db()
    ticket = await db.support_tickets.find_one_and_update(
        {"id": ticket_id},
        {"$set": {"status": "closed", "closed_at": utc_now(), "closed_by": staff["id"]}},
        projection={"_id": 0}, return_document=True,
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    await audit.write(staff["id"], "admin.ticket_closed", f"ticket:{ticket_id}", {})
    return jsonable_encoder(ticket)


# ---------- System health (C.6) ----------

@router.get("/health")
async def system_health(staff: dict = Depends(_require_admin)):
    db = get_db()
    counts = {}
    for coll in ["users", "jobs", "applications", "submission_receipts",
                 "outcomes", "interviews", "manual_queue_items",
                 "authorization_scopes", "ai_generations", "audit_events",
                 "consent_records", "subscriptions", "payment_transactions",
                 "export_jobs", "support_tickets", "feature_flags"]:
        counts[coll] = await db[coll].count_documents({})
    # LLM cost aggregate
    cost_agg = [c async for c in db.llm_costs.aggregate([
        {"$group": {"_id": "$model", "cost_usd": {"$sum": "$cost_usd"}, "n": {"$sum": 1}}},
    ])]
    return {"counts": counts, "llm_costs": jsonable_encoder(cost_agg),
            "queue_depth_stub": counts.get("manual_queue_items", 0)}


# ---------- Observability (C.7) — labeled STUB ----------

@router.get("/observability/events")
async def list_internal_events(limit: int = 50, staff: dict = Depends(_require_admin)):
    events = [e async for e in get_db().internal_analytics_events.find({}, {"_id": 0}).sort("ts", -1).limit(limit)]
    return {"events": jsonable_encoder(events),
            "label": "INTERNAL STUB — PostHog equivalent. Not wired to any external analytics.",
            "count": len(events)}


class TestErrorBody(BaseModel):
    where: str = "manual_admin_test"


@router.post("/observability/test-error")
async def emit_test_error(body: TestErrorBody, staff: dict = Depends(_require_admin_only)):
    db = get_db()
    doc = {
        "id": str(uuid.uuid4()),
        "ts": utc_now(),
        "actor_id": staff["id"],
        "kind": "test_error",
        "where": body.where,
        "message": "Admin-emitted test error (labeled stub).",
        "label": "INTERNAL STUB — Sentry equivalent. Not sent to any external error-tracking service.",
    }
    await db.internal_error_events.insert_one(doc)
    return {"emitted": True, "id": doc["id"], "label": doc["label"]}


@router.get("/observability/errors")
async def list_test_errors(staff: dict = Depends(_require_admin)):
    errs = [e async for e in get_db().internal_error_events.find({}, {"_id": 0}).sort("ts", -1).limit(50)]
    return {"errors": jsonable_encoder(errs),
            "label": "INTERNAL STUB — Sentry equivalent. Not sent to any external error-tracking service."}

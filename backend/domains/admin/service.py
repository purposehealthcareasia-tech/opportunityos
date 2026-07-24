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
from core.config import settings
from domains.audit import service as audit
from domains.subscriptions import service as subs_svc
from services import plans as plans_svc


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


SEALED_MASK = "•••• (sealed)"
REFUND_REASONS = {"duplicate_charge", "customer_request", "billing_error", "goodwill", "policy_bounded_first_purchase"}

# Fields that must NEVER leave the server via any admin-facing serialization.
# Add here whenever a new credential/secret column is introduced.
SENSITIVE_USER_FIELDS = {"password_hash", "password", "totp_secret", "recovery_codes"}


def _sanitize_user(row: dict | None) -> dict | None:
    """Strip credential/secret material before returning a user document to
    admin / support. This is the last line of defence against a P0 leak — the
    projection helpers above already exclude these, but any future ad-hoc
    `find` that forgets the projection is caught here too."""
    if not row:
        return row
    return {k: v for k, v in row.items() if k not in SENSITIVE_USER_FIELDS}


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
    UI can still show the type/label/status. No unmask path exists in v0.1."""
    if (claim.get("sensitivity") or "").lower() == "sealed":
        return {**claim, "value": SEALED_MASK}
    return claim


# Fields on eligibility_profile that carry actual eligibility data. Everything
# NOT in this set is treated as structural (id/user_id/version/updated_at/
# sensitivity) and passes through so the UI can still render the shell.
_ELIG_DATA_FIELDS = {"status", "dates", "notes", "derived_flags", "opt_end",
                     "earliest_start", "work_auth", "sponsorship"}


def _mask_sealed_profile(profile: dict | None) -> dict | None:
    """Mask sealed eligibility_profile fields with `SEALED_MASK`. If the profile
    is not marked sealed we pass it through unchanged so we can still surface
    non-sealed rows (e.g., legacy imports). All new profiles are sealed by
    default in v0.1."""
    if not profile:
        return profile
    if (profile.get("sensitivity") or "").lower() != "sealed":
        return profile
    masked = dict(profile)
    for k in list(masked.keys()):
        if k in _ELIG_DATA_FIELDS:
            masked[k] = SEALED_MASK
    return masked


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
    # Projection excludes credential fields at the driver level; _sanitize_user
    # scrubs again after the fetch (defence-in-depth).
    row = await db.users.find_one(
        {"id": user_id},
        {"_id": 0, **{f: 0 for f in SENSITIVE_USER_FIELDS}},
    )
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")
    row = _sanitize_user(row)
    # Sealed masking on claims — value replaced with SEALED_MASK when sensitivity=sealed.
    claims_raw = [c async for c in db.claims.find({"user_id": user_id}, {"_id": 0})]
    claims = [_mask_sealed(c) for c in claims_raw]
    # Sealed masking on the eligibility_profile (latest version). Structural
    # fields pass through so the UI can render the shell; data fields become
    # SEALED_MASK. No unmask path.
    elig_raw = await db.eligibility_profiles.find_one(
        {"user_id": user_id}, {"_id": 0}, sort=[("version", -1)],
    )
    eligibility_profile = _mask_sealed_profile(elig_raw)
    sub = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    apps_count = await db.applications.count_documents({"user_id": user_id})
    receipts_count = await db.submission_receipts.count_documents({"user_id": user_id})
    await audit.write(staff["id"], "admin.user_detail_view", f"user:{user_id}",
                      {"staff_role": staff.get("role")})
    return jsonable_encoder({
        "user": row,
        "claims": claims,
        "eligibility_profile": eligibility_profile,
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


# ---------- Plan grant (comp / migration / support tool) ----------
# Admin-only path to set a user's subscription plan directly, bypassing Stripe.
# Use cases: founder self-comp, migration from legacy plans, support-desk
# escalations for VIPs or partner accounts. Idempotent by design — repeating
# the same grant is a no-op that still writes an audit row so we retain the
# ledger of who asked when.

class GrantPlanBody(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=200,
                          description="Target user id (uuid).")
    plan_slug: str = Field(..., description="Plan slug: one of free|plus|pro|max.")
    note: str = Field(default="", max_length=1000,
                       description="Free-text audit note (why the grant was issued).")


@router.post("/subscriptions/grant")
async def admin_grant_plan(body: GrantPlanBody,
                           staff: dict = Depends(_require_admin_only)):
    """Grant / set a user's subscription plan directly. Admin-only, audited,
    idempotent. Does NOT touch Stripe — see /api/v1/billing/checkout for the
    paid flow. Intended for comp accounts, migrations, and support escalations."""
    plan_slug = (body.plan_slug or "").strip().lower()
    if plan_slug not in plans_svc.PLANS:
        raise HTTPException(status_code=400, detail={
            "error": "invalid_plan_slug",
            "allowed": sorted(plans_svc.PLANS.keys()),
        })
    db = get_db()
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0, "id": 1, "email": 1})
    if not user:
        raise HTTPException(status_code=404, detail={"error": "user_not_found"})

    existing = await db.subscriptions.find_one({"user_id": body.user_id},
                                                 {"_id": 0, "plan": 1, "id": 1})
    previous_plan = (existing or {}).get("plan")
    already_on_plan = previous_plan == plan_slug

    sub = await subs_svc.set_plan(body.user_id, plan_slug,
                                     actor=f"admin:{staff['id']}")

    await audit.write(
        staff["id"],
        "admin.plan_granted",
        f"user:{body.user_id}",
        {
            "plan": plan_slug,
            "previous_plan": previous_plan,
            "already_on_plan": already_on_plan,
            "note": body.note,
        },
    )
    return {
        "granted": not already_on_plan,
        "already_on_plan": already_on_plan,
        "plan": plan_slug,
        "previous_plan": previous_plan,
        "subscription_id": sub.get("id"),
        "user_id": body.user_id,
    }


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
    # Fire push notification to the ticket owner.
    if ticket.get("user_id"):
        from domains.notifications import events as notif_events
        await notif_events.on_support_ticket_replied(ticket["user_id"], ticket_id)
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
                 "authorization_scopes", "ai_generations", "audit_logs",
                 "consent_records", "subscriptions", "payment_transactions",
                 "export_jobs", "support_tickets", "feature_flags"]:
        counts[coll] = await db[coll].count_documents({})
    # LLM cost aggregate
    cost_agg = [c async for c in db.llm_costs.aggregate([
        {"$group": {"_id": "$model", "cost_usd": {"$sum": "$cost_usd"}, "n": {"$sum": 1}}},
    ])]
    return {"counts": counts, "llm_costs": jsonable_encoder(cost_agg),
            "queue_depth_stub": counts.get("manual_queue_items", 0),
            # SEC-004(d) — deploy-flag disclosure lives HERE, behind admin auth,
            # not on the public `/api/health`.
            "prod_mode": bool(settings.PROD_MODE),
            "ci_test_issuer_enabled": bool(settings.CI_TEST_ISSUER_ENABLED),
            # Ops visibility — what commit is actually running in this pod.
            "build_sha": _read_build_sha()}


def _read_build_sha() -> str:
    """Best-effort build/commit SHA for admin ops visibility.

    Preference order:
      1. `BUILD_SHA` env var (set by CI/CD).
      2. First 12 chars of the top line of `/app/.git/HEAD` → resolved.
      3. `unknown` — never raises.
    """
    import os
    v = (os.environ.get("BUILD_SHA") or "").strip()
    if v:
        return v[:40]
    try:
        head = open("/app/.git/HEAD", "r", encoding="utf-8").read().strip()
        if head.startswith("ref:"):
            ref_path = head.split(" ", 1)[1].strip()
            sha = open(f"/app/.git/{ref_path}", "r", encoding="utf-8").read().strip()
            return sha[:40]
        return head[:40]
    except Exception:
        return "unknown"


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

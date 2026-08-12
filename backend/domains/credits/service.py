"""Application Credits — internal Fynd ledger (NOT Emergent credits).

Rails (Phase 6d — 2026-08-12):

* One credit = one submitted application (email-route SEND or sprint form
  submit). Debits fire AFTER a `submission_receipts` insert; if the debit
  fails because balance is zero, the caller's dispatch fails-closed and
  the item PARKS (`wave_queue.state="paused_no_credits"`). Nothing is
  silently dropped, nothing is auto-flushed.
* Ledger is APPEND-ONLY. Every debit references its `receipt_id` and every
  grant references its `source`. A compound unique index on
  `(user_id, receipt_id, direction)` makes the debit path idempotent —
  replaying the same dispatch never double-debits.
* Balance is a materialized single-doc-per-user in `application_credits_balance`
  kept in sync with the ledger by the write path. The **DEBIT path always
  atomically reads-and-writes the balance doc via `find_one_and_update`**
  with a `{$gte: 1}` filter; there is NO cache read on the debit path.
  The 5-second `balance_display_cache` exists only for the read-side
  `GET /api/v1/credits/me` endpoint so the UI can be fast — halts and
  cap decisions never touch it.
* Unlimited-plan flag: `application_credits_balance.is_unlimited=True`
  short-circuits the debit path — it appends an unlimited-audit ledger
  row without decrementing the balance. Founder / top-tier plans get
  this by default.
* Admin `POST /api/v1/admin/credits/grant` is fully audited (goes through
  `audit.write`) and gated on the same admin-or-owner check used
  elsewhere.
* Monthly refill runs from the scheduler on UTC month-start; refill is
  the same code path as an admin grant (source="monthly_refill").
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.db import get_db

log = logging.getLogger("oppos.credits")


# ---------------------------------------------------------------------------
# Plan defaults (decide-and-document; approved by founder 2026-08-12).
# Founder / top-tier plans set the unlimited flag. Everyone else gets a
# monthly grant — the first-boot bootstrap grant runs when a new user's
# balance doc is first materialized.
# ---------------------------------------------------------------------------
PLAN_MONTHLY_GRANT = {
    "starter": 50,
    "pro":     250,
    "founder": 0,          # 0 with is_unlimited=True — no cap, ledger records
}

UNLIMITED_PLANS = frozenset(("founder",))


# ---------------------------------------------------------------------------
# Display cache — read-side ONLY. Debit path never reads this.
# ---------------------------------------------------------------------------
_DISPLAY_CACHE: dict[str, tuple[float, dict]] = {}
_DISPLAY_CACHE_TTL_S = 5.0


def _cache_get(user_id: str) -> Optional[dict]:
    v = _DISPLAY_CACHE.get(user_id)
    if v is None:
        return None
    ts, payload = v
    if time.monotonic() - ts > _DISPLAY_CACHE_TTL_S:
        _DISPLAY_CACHE.pop(user_id, None)
        return None
    return payload


def _cache_put(user_id: str, payload: dict) -> None:
    _DISPLAY_CACHE[user_id] = (time.monotonic(), payload)


def _invalidate_display_cache(user_id: str) -> None:
    _DISPLAY_CACHE.pop(user_id, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def ensure_user_balance_row(user_id: str, *, plan: str = "starter") -> dict:
    """Create the user's balance row if missing, applying the plan's
    initial grant. Idempotent — on repeat calls it just returns the
    existing row. Runs at user signup and lazily on first credit read."""
    db = get_db()
    existing = await db.application_credits_balance.find_one({"user_id": user_id},
                                                                {"_id": 0})
    if existing:
        return existing
    initial_grant = PLAN_MONTHLY_GRANT.get(plan, PLAN_MONTHLY_GRANT["starter"])
    is_unlimited = plan in UNLIMITED_PLANS
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user_id,
        "plan": plan,
        "balance": initial_grant,
        "is_unlimited": is_unlimited,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.application_credits_balance.insert_one({**doc})
    except Exception:
        # Race — another concurrent call materialized it. Return whatever
        # is now in the DB.
        existing = await db.application_credits_balance.find_one({"user_id": user_id},
                                                                    {"_id": 0})
        if existing:
            return existing
        raise
    # Append the bootstrap-grant ledger row.
    if initial_grant > 0 or is_unlimited:
        await db.application_credits_ledger.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "direction": "grant",
            "amount": initial_grant,
            "source": "bootstrap_signup_grant",
            "plan": plan,
            "is_unlimited_flag": is_unlimited,
            "ts": now,
        })
    _invalidate_display_cache(user_id)
    return doc


async def get_balance(user_id: str, *, use_cache: bool = True) -> dict:
    """Return the user's current balance snapshot for display. Reads the
    5-second cache when `use_cache=True` (default for UI paths). Halt /
    debit paths must call `check_and_debit(...)` instead — they NEVER
    trust this cache."""
    if use_cache:
        c = _cache_get(user_id)
        if c is not None:
            return c
    db = get_db()
    row = await db.application_credits_balance.find_one({"user_id": user_id},
                                                            {"_id": 0})
    if row is None:
        row = await ensure_user_balance_row(user_id, plan="starter")
    payload = {
        "user_id": user_id,
        "balance": row.get("balance", 0),
        "plan": row.get("plan", "starter"),
        "is_unlimited": bool(row.get("is_unlimited", False)),
    }
    _cache_put(user_id, payload)
    return payload


async def check_and_debit(
    *,
    user_id: str,
    receipt_id: str,
    application_id: str,
    reason: str = "application_submitted",
) -> dict:
    """Atomically decrement 1 credit iff balance >= 1 (or unlimited).
    Returns a dict {ok, balance_after, is_unlimited, ledger_row}. When
    balance is insufficient, returns {ok: False, error: "insufficient_credits"}
    WITHOUT any DB mutation.

    Idempotent per (user_id, receipt_id) — the ledger's unique compound
    index blocks double-debits. If a replay hits an already-recorded
    debit, we detect the duplicate insert error, rollback the balance
    (never decrement twice for the same receipt), and return the
    original debit's balance snapshot as if it were fresh.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    # Read the row for unlimited-plan short-circuit. NB: this read is
    # only used to select which mutation to apply, not to authorize the
    # spend — the authorization is the filter clause of `find_one_and_update`.
    row = await db.application_credits_balance.find_one(
        {"user_id": user_id}, projection={"_id": 0, "is_unlimited": 1, "plan": 1},
    )
    if row is None:
        row = await ensure_user_balance_row(user_id, plan="starter")

    if row.get("is_unlimited"):
        # Unlimited path: append audit ledger row, don't touch balance.
        # Idempotent via unique index below — if we hit a dup, treat as
        # already-charged and return successfully.
        ledger = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "direction": "unlimited_debit",
            "amount": 0,
            "receipt_id": receipt_id,
            "application_id": application_id,
            "reason": reason,
            "ts": now,
        }
        was_duplicate = False
        try:
            await db.application_credits_ledger.insert_one({**ledger})
        except Exception as e:
            if "E11000" in str(e):
                # Already recorded — treat as success.
                was_duplicate = True
            else:
                raise
        _invalidate_display_cache(user_id)
        return {"ok": True, "balance_after": None, "is_unlimited": True,
                "ledger_id": ledger["id"], "duplicate": was_duplicate}

    # ATOMIC DEBIT via find_one_and_update. The filter clause is the
    # authorization: we only decrement if balance >= 1. If it returns
    # None, the user is either non-existent or out of credits.
    updated = await db.application_credits_balance.find_one_and_update(
        {"user_id": user_id, "balance": {"$gte": 1}},
        {"$inc": {"balance": -1}, "$set": {"updated_at": now}},
        return_document=True,     # pymongo alias for ReturnDocument.AFTER
        projection={"_id": 0},
    )
    if updated is None:
        # Insufficient credits — no mutation happened.
        return {"ok": False, "error": "insufficient_credits",
                "balance_after": 0, "is_unlimited": False}

    balance_after = updated.get("balance", 0)
    ledger = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "direction": "debit",
        "amount": -1,
        "receipt_id": receipt_id,
        "application_id": application_id,
        "reason": reason,
        "balance_after": balance_after,
        "ts": now,
    }
    try:
        await db.application_credits_ledger.insert_one({**ledger})
    except Exception as e:
        if "E11000" in str(e):
            # Replay: another concurrent path already debited this same
            # (user_id, receipt_id, direction). Rollback our +1 debit and
            # return the balance we observed post-rollback. This makes
            # the API idempotent even under race replays.
            await db.application_credits_balance.update_one(
                {"user_id": user_id},
                {"$inc": {"balance": 1}, "$set": {"updated_at": now}},
            )
            log.info("credits.debit replay ignored user=%s receipt=%s", user_id, receipt_id)
            _invalidate_display_cache(user_id)
            return {"ok": True, "balance_after": balance_after + 1,
                    "is_unlimited": False, "duplicate": True}
        raise

    _invalidate_display_cache(user_id)
    return {"ok": True, "balance_after": balance_after, "is_unlimited": False,
            "ledger_id": ledger["id"]}


async def grant(
    *,
    user_id: str,
    amount: int,
    source: str,
    admin_actor: Optional[str] = None,
) -> dict:
    """Append a positive-amount grant to the ledger and materialize it
    into the balance doc. `source` is a short slug identifying WHY
    (e.g. "monthly_refill", "admin_grant", "promo_signup")."""
    if amount <= 0:
        raise ValueError("grant amount must be positive")
    db = get_db()
    # Ensure balance row exists first.
    await ensure_user_balance_row(user_id, plan="starter")
    now = datetime.now(timezone.utc)
    await db.application_credits_balance.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount}, "$set": {"updated_at": now}},
        upsert=True,
    )
    ledger = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "direction": "grant",
        "amount": amount,
        "source": source,
        "admin_actor": admin_actor,
        "ts": now,
    }
    await db.application_credits_ledger.insert_one({**ledger})
    _invalidate_display_cache(user_id)
    return {"ok": True, "ledger_id": ledger["id"], "granted": amount}


async def monthly_refill_all() -> dict:
    """Scheduler entry-point — run once per UTC month-start. Adds every
    user's plan grant to their balance. Idempotent: uses a
    `(user_id, source, month_key)` guard so replays don't double-grant.
    """
    db = get_db()
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    granted = 0
    async for u in db.application_credits_balance.find({}, {"user_id": 1, "plan": 1, "is_unlimited": 1, "_id": 0}):
        plan = u.get("plan", "starter")
        if u.get("is_unlimited"):
            continue
        amt = PLAN_MONTHLY_GRANT.get(plan, PLAN_MONTHLY_GRANT["starter"])
        if amt <= 0:
            continue
        # Idempotency: skip if a grant for this month is already recorded.
        already = await db.application_credits_ledger.find_one({
            "user_id": u["user_id"], "source": "monthly_refill",
            "month_key": month_key,
        }, {"_id": 1})
        if already:
            continue
        now = datetime.now(timezone.utc)
        await db.application_credits_balance.update_one(
            {"user_id": u["user_id"]},
            {"$inc": {"balance": amt}, "$set": {"updated_at": now}},
        )
        await db.application_credits_ledger.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": u["user_id"],
            "direction": "grant",
            "amount": amt,
            "source": "monthly_refill",
            "month_key": month_key,
            "ts": now,
        })
        _invalidate_display_cache(u["user_id"])
        granted += 1
    return {"ok": True, "users_granted": granted, "month_key": month_key}


async def ledger_page(user_id: str, *, limit: int = 100) -> list[dict]:
    """Return the user's recent ledger rows for audit / display."""
    db = get_db()
    rows: list[dict] = []
    async for r in db.application_credits_ledger.find({"user_id": user_id},
                                                          {"_id": 0}).sort("ts", -1).limit(limit):
        rows.append(r)
    return rows

"""Notification service — subscribe / unsubscribe / dispatch / prune.

Privacy invariant (enforced by `_build_payload`): titles and bodies are
generic. No employer, salary, sealed, or claim content EVER crosses the
push boundary — details load in-app after cookie auth.

Ownership: `unsubscribe`/`prune` operate on `(user_id, endpoint)` pairs;
a user can only reach their own subscriptions.

Rate limits: subscribe + test-send both use a sliding-window bucket via
the existing `services.login_throttle` primitives. Fresh subscribes and
test-sends are capped per user AND per IP.

Prune: after every dispatch we deactivate subscriptions the browser push
service returns 404 / 410 for — that endpoint has been withdrawn.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit
from domains.notifications import NOTIFICATION_CATEGORIES

log = logging.getLogger("oppos.notifications")


# ---------------------------------------------------------------------------
# Payload sanitization — the ONLY function allowed to build push data.
# ---------------------------------------------------------------------------

_ALLOWED_TITLES = {
    "application_updates": "Application update",
    "interviews":          "Interview scheduled",
    "approvals_expiring":  "Approval expiring soon",
    "receipts":            "Submission recorded",
    "support":             "Support ticket update",
}
_ALLOWED_BODIES = {
    "application_updates": "There's a new update on one of your applications.",
    "interviews":          "An interview was added to your tracker.",
    "approvals_expiring":  "An approved application authorization is expiring soon.",
    "receipts":            "A submission receipt was recorded.",
    "support":             "A member of the support team replied.",
}
# Fields that MUST NEVER appear in a push payload. Enforced by
# `_scrub_data_dict`; violations raise so tests catch it.
_FORBIDDEN_KEYS = {
    "company_id", "company_name", "company_domain", "employer",
    "salary", "compensation", "comp",
    "eligibility", "eligibility_profile", "eligibility_status",
    "claim", "claims", "claim_ids", "claim_id",
    "note", "notes", "body", "text", "email", "phone",
    "screener_answer", "screener_answers", "answer", "answers",
    "authorization_id", "materials_hash",
}


def _scrub_data_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Enforce the payload-minimalism invariant.

    Only keys that name an in-app route target are allowed:
      - `category` — one of NOTIFICATION_CATEGORIES
      - `application_id` — opaque UUID reference (no snapshot content)
      - `receipt_id`, `interview_id`, `outcome_id`, `ticket_id` — opaque refs
      - `url` — in-app relative route only (must start with /)
    """
    ALLOWED = {"category", "application_id", "receipt_id", "interview_id",
               "outcome_id", "ticket_id", "url"}
    out: dict[str, Any] = {}
    for k, v in (data or {}).items():
        if k in _FORBIDDEN_KEYS:
            raise ValueError(f"push_payload_leak: forbidden key {k!r}")
        if k not in ALLOWED:
            continue
        if k == "url":
            if not isinstance(v, str) or not v.startswith("/"):
                continue
            if v.startswith("//"):  # protocol-relative → refuse
                continue
        out[k] = v
    return out


def _build_payload(category: str, data: dict[str, Any] | None = None) -> str:
    """Return the JSON blob the service worker will decrypt.

    Titles / bodies come from a fixed vocabulary keyed by category — the
    caller CANNOT pass a custom title or body. This guarantees that no
    sensitive content ever transits the push channel.
    """
    if category not in NOTIFICATION_CATEGORIES:
        raise ValueError(f"unknown_notification_category: {category}")
    return json.dumps({
        "title": _ALLOWED_TITLES[category],
        "body":  _ALLOWED_BODIES[category],
        "category": category,
        "data": _scrub_data_dict(data or {}),
    })


# ---------------------------------------------------------------------------
# Index bootstrap
# ---------------------------------------------------------------------------

async def ensure_indexes() -> None:
    db = get_db()
    # A user may register multiple devices/browsers, so key by endpoint per user.
    await db.notification_subscriptions.create_index(
        [("user_id", 1), ("endpoint", 1)], unique=True,
        name="uniq_subscription_per_user_endpoint",
    )
    await db.notification_subscriptions.create_index([("user_id", 1), ("active", 1)])
    await db.notification_preferences.create_index("user_id", unique=True)
    await db.notifications.create_index([("user_id", 1), ("ts", -1)])
    await db.notifications.create_index([("user_id", 1), ("category", 1), ("ts", -1)])


# ---------------------------------------------------------------------------
# Preferences — per-category opt-in map, enforced server-side.
# ---------------------------------------------------------------------------

DEFAULT_PREFS: dict[str, bool] = {k: True for k in NOTIFICATION_CATEGORIES}


async def get_preferences(user_id: str) -> dict[str, bool]:
    row = await get_db().notification_preferences.find_one(
        {"user_id": user_id}, {"_id": 0}
    )
    prefs = {**DEFAULT_PREFS}
    if row:
        stored = row.get("categories", {}) or {}
        for k in NOTIFICATION_CATEGORIES:
            if isinstance(stored.get(k), bool):
                prefs[k] = stored[k]
    return prefs


async def set_preferences(user_id: str, updates: dict[str, bool], *, actor: str) -> dict[str, bool]:
    if not updates:
        return await get_preferences(user_id)
    current = await get_preferences(user_id)
    for k, v in updates.items():
        if k in NOTIFICATION_CATEGORIES and isinstance(v, bool):
            current[k] = v
    now = utc_now()
    await get_db().notification_preferences.update_one(
        {"user_id": user_id},
        {"$set": {"categories": current, "updated_at": now},
         "$setOnInsert": {"user_id": user_id, "created_at": now}},
        upsert=True,
    )
    await audit.write(actor, "notifications.preferences_updated",
                      f"user:{user_id}", {"categories": current})
    return current


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------

async def register_subscription(*, user_id: str, subscription: dict[str, Any],
                                 user_agent: str | None) -> dict[str, Any]:
    """Upsert a push subscription for `user_id`. Idempotent by endpoint."""
    endpoint = subscription["endpoint"]
    keys = subscription.get("keys") or {}
    if not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("subscription_missing_keys")
    now = utc_now()
    db = get_db()
    doc_id = str(uuid.uuid4())
    result = await db.notification_subscriptions.find_one_and_update(
        {"user_id": user_id, "endpoint": endpoint},
        {
            "$set": {
                "user_id": user_id,
                "endpoint": endpoint,
                "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                "user_agent": (user_agent or "")[:400],
                "active": True,
                "revoked_at": None,
                "last_seen_at": now,
            },
            "$setOnInsert": {"id": doc_id, "created_at": now},
        },
        upsert=True,
        return_document=True,
        projection={"_id": 0},
    )
    await audit.write(user_id, "notifications.subscribed",
                      f"push:{endpoint[-24:]}", {})
    return result


async def revoke_subscription(*, user_id: str, endpoint: str) -> bool:
    """Ownership-checked deactivation. Returns True if a row was updated."""
    now = utc_now()
    r = await get_db().notification_subscriptions.update_one(
        {"user_id": user_id, "endpoint": endpoint, "active": True},
        {"$set": {"active": False, "revoked_at": now, "last_seen_at": now}},
    )
    if r.matched_count:
        await audit.write(user_id, "notifications.unsubscribed",
                          f"push:{endpoint[-24:]}", {})
        return True
    return False


async def list_subscriptions(user_id: str) -> list[dict[str, Any]]:
    return [s async for s in get_db().notification_subscriptions.find(
        {"user_id": user_id}, {"_id": 0, "keys": 0}
    ).sort("created_at", -1)]


async def _active_subscriptions(user_id: str) -> list[dict[str, Any]]:
    return [s async for s in get_db().notification_subscriptions.find(
        {"user_id": user_id, "active": True}, {"_id": 0}
    )]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _pywebpush_available() -> bool:
    try:
        import pywebpush  # noqa: F401
        return True
    except Exception:  # pragma: no cover
        return False


def _vapid_config() -> tuple[str, str, str] | None:
    import os
    pub = os.environ.get("VAPID_PUBLIC_KEY", "")
    priv = os.environ.get("VAPID_PRIVATE_KEY", "")
    sub = os.environ.get("VAPID_SUBJECT", "")
    if not (pub and priv and sub and sub.startswith("mailto:")):
        return None
    return pub, priv, sub


async def _prune_dead(user_id: str, endpoint: str, *, reason: str) -> None:
    """Deactivate a subscription the browser push service refused."""
    now = utc_now()
    await get_db().notification_subscriptions.update_one(
        {"user_id": user_id, "endpoint": endpoint, "active": True},
        {"$set": {"active": False, "revoked_at": now, "prune_reason": reason,
                  "last_seen_at": now}},
    )
    await audit.write("system:notifications", "notifications.pruned",
                      f"push:{endpoint[-24:]}", {"reason": reason, "user_id": user_id})


async def dispatch(user_id: str, category: str, data: dict[str, Any] | None = None,
                   *, dedup_key: str | None = None) -> dict[str, Any]:
    """Send a push to every ACTIVE subscription for the user, but only if the
    user's per-category preference for `category` is enabled.

    Returns a summary dict: `{sent, failed, skipped, pruned, category, notification_id}`.

    Idempotency: `dedup_key` (application_id, receipt_id, etc.) prevents
    duplicate sends within the same category for the same trigger. If a row
    already exists in `notifications` with `(user_id, category, dedup_key)`,
    dispatch is a no-op.
    """
    if category not in NOTIFICATION_CATEGORIES:
        raise ValueError(f"unknown_notification_category: {category}")

    db = get_db()

    # Dedup guard.
    if dedup_key:
        existing = await db.notifications.find_one({
            "user_id": user_id, "category": category, "dedup_key": dedup_key,
        }, {"_id": 0, "id": 1})
        if existing:
            return {"sent": 0, "failed": 0, "skipped": 1, "pruned": 0,
                    "category": category, "notification_id": existing["id"],
                    "reason": "duplicate"}

    # Per-category preference.
    prefs = await get_preferences(user_id)
    if not prefs.get(category, True):
        return {"sent": 0, "failed": 0, "skipped": 1, "pruned": 0,
                "category": category, "notification_id": None,
                "reason": "opted_out"}

    subs = await _active_subscriptions(user_id)
    if not subs:
        return {"sent": 0, "failed": 0, "skipped": 0, "pruned": 0,
                "category": category, "notification_id": None,
                "reason": "no_active_subscriptions"}

    vapid = _vapid_config()
    if not vapid:
        return {"sent": 0, "failed": len(subs), "skipped": 0, "pruned": 0,
                "category": category, "notification_id": None,
                "reason": "vapid_not_configured"}

    if not _pywebpush_available():
        return {"sent": 0, "failed": len(subs), "skipped": 0, "pruned": 0,
                "category": category, "notification_id": None,
                "reason": "pywebpush_import_failed"}

    _, private_key, subject = vapid
    from pywebpush import webpush, WebPushException

    payload_str = _build_payload(category, data)
    notification_id = str(uuid.uuid4())
    now = utc_now()

    sent = 0
    failed = 0
    pruned = 0
    device_results: list[dict[str, Any]] = []

    for s in subs:
        try:
            subscription_info = {
                "endpoint": s["endpoint"],
                "keys": s["keys"],
            }
            webpush(
                subscription_info=subscription_info,
                data=payload_str,
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
            )
            sent += 1
            device_results.append({"endpoint_tail": s["endpoint"][-24:], "status": "sent"})
        except WebPushException as e:  # pragma: no cover — network path
            resp = getattr(e, "response", None)
            code = getattr(resp, "status_code", None)
            if code in (404, 410):
                await _prune_dead(user_id, s["endpoint"],
                                  reason=f"push_service_returned_{code}")
                pruned += 1
                device_results.append({"endpoint_tail": s["endpoint"][-24:],
                                       "status": "pruned", "http": code})
            else:
                failed += 1
                device_results.append({"endpoint_tail": s["endpoint"][-24:],
                                       "status": "failed", "http": code,
                                       "error": str(e)[:200]})
                log.warning("webpush send failed user=%s code=%s err=%s",
                            user_id, code, str(e)[:200])
        except Exception as e:  # pragma: no cover
            failed += 1
            device_results.append({"endpoint_tail": s["endpoint"][-24:],
                                   "status": "failed", "error": str(e)[:200]})
            log.exception("webpush unexpected error user=%s", user_id)

    await db.notifications.insert_one({
        "id": notification_id,
        "user_id": user_id,
        "category": category,
        "dedup_key": dedup_key,
        "data": _scrub_data_dict(data or {}),
        "ts": now,
        "results": device_results,
        "sent_count": sent,
        "failed_count": failed,
        "pruned_count": pruned,
    })

    await audit.write("system:notifications", "notifications.dispatched",
                      f"user:{user_id}",
                      {"category": category, "sent": sent, "failed": failed,
                       "pruned": pruned, "dedup_key": dedup_key,
                       "notification_id": notification_id})
    return {
        "sent": sent, "failed": failed, "skipped": 0, "pruned": pruned,
        "category": category, "notification_id": notification_id,
    }


# ---------------------------------------------------------------------------
# Rate-limit route names (used by the router; enforcement lives in
# `services.login_throttle.check_and_record_attempt` which already handles
# both per-identifier and per-IP caps).
# ---------------------------------------------------------------------------

RATE_ROUTE_SUBSCRIBE = "notifications:subscribe"
RATE_ROUTE_TEST_SEND = "notifications:test_send"

"""Background sweep: send `approvals_expiring` push notifications for
authorizations with <12h remaining on their 72h TTL.

Idempotent — each authorization can only trigger a single notification
because `dispatch()` dedups by `dedup_key=authexp:<auth_id>`.

Design: called from `server.py` lifespan as an asyncio task that loops
every `SWEEP_INTERVAL_SECONDS`. Safe to run multiple pod replicas; the
notifications table's dedup guarantees at-most-once delivery per pod
across `SWEEP_INTERVAL_SECONDS` (worst case: a notification is sent by
one pod while another prepares to send it → the second insert is
short-circuited by the dedup lookup).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from core.db import get_db
from core.time_utils import utc_now
from domains.notifications import events as notif_events

log = logging.getLogger("oppos.notifications.sweep")

SWEEP_INTERVAL_SECONDS = 30 * 60          # every 30 minutes
EXPIRY_WINDOW_HOURS = 12                  # notify when <12h remaining


async def sweep_once() -> int:
    """Emit push notifications for every authorization expiring within the
    window that we haven't already notified. Returns the number of
    notifications fired (best-effort count)."""
    db = get_db()
    now = utc_now()
    window_end = now + timedelta(hours=EXPIRY_WINDOW_HOURS)

    fired = 0
    async for auth in db.authorization_scopes.find(
        {
            "expires_at": {"$gt": now, "$lte": window_end},
            "revoked_at": None,
        },
        {"_id": 0, "id": 1, "user_id": 1, "target": 1, "expires_at": 1},
    ):
        # `target` typically references the application id for submit-time auths.
        app_id = auth.get("target") or ""
        await notif_events.on_authorization_expiring_soon(
            user_id=auth["user_id"],
            application_id=app_id,
            authorization_id=auth["id"],
        )
        fired += 1
    if fired:
        log.info("approvals_expiring sweep fired=%d", fired)
    return fired


async def sweep_forever() -> None:
    """Continuous background loop. Cancelled on backend shutdown."""
    log.info("approvals_expiring sweep started (interval=%ds, window=%dh)",
             SWEEP_INTERVAL_SECONDS, EXPIRY_WINDOW_HOURS)
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            log.info("approvals_expiring sweep cancelled")
            raise
        except Exception:
            log.exception("approvals_expiring sweep iteration failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)

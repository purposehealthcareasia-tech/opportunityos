"""Notification event triggers.

Every domain that mutates an application/interview/receipt/support-ticket
calls one of these helpers AFTER its own state change commits. Notification
failures are logged but NEVER raise back to the caller — a push send failing
must not fail the user's action.

Privacy invariant: these helpers pass only opaque reference IDs to
`svc.dispatch`; the service enforces payload minimalism via `_scrub_data_dict`.
"""
from __future__ import annotations

import logging
from typing import Any

from domains.notifications import service as svc

log = logging.getLogger("oppos.notifications.events")


async def _safe_dispatch(user_id: str, category: str, data: dict[str, Any],
                        dedup_key: str) -> None:
    try:
        await svc.dispatch(user_id, category, data, dedup_key=dedup_key)
    except Exception:
        log.exception("notification dispatch failed user=%s category=%s dedup=%s",
                      user_id, category, dedup_key)


async def on_outcome_logged(user_id: str, application_id: str, outcome_id: str,
                            event: str) -> None:
    """`event` is one of: viewed | response | interview_request |
    interview_scheduled | rejected | offer | hired | closed.

    Interview stage handled by `on_interview_scheduled`; here we notify on
    material application state moves only.
    """
    NOTIFY_EVENTS = {"response", "rejected", "offer", "hired", "closed"}
    if event not in NOTIFY_EVENTS:
        return
    await _safe_dispatch(
        user_id, "application_updates",
        data={"application_id": application_id, "outcome_id": outcome_id,
              "url": "/tracker"},
        dedup_key=f"outcome:{outcome_id}",
    )


async def on_interview_scheduled(user_id: str, application_id: str,
                                 interview_id: str) -> None:
    await _safe_dispatch(
        user_id, "interviews",
        data={"application_id": application_id, "interview_id": interview_id,
              "url": "/tracker"},
        dedup_key=f"interview:{interview_id}",
    )


async def on_receipt_created(user_id: str, application_id: str,
                             receipt_id: str) -> None:
    await _safe_dispatch(
        user_id, "receipts",
        data={"application_id": application_id, "receipt_id": receipt_id,
              "url": "/tracker"},
        dedup_key=f"receipt:{receipt_id}",
    )


async def on_authorization_expiring_soon(user_id: str, application_id: str,
                                         authorization_id: str) -> None:
    """Fires when an authorization has <12h remaining on its 72h TTL and
    hasn't already been notified. Dedup key includes the auth id so the
    same authorization never triggers twice.
    """
    await _safe_dispatch(
        user_id, "approvals_expiring",
        data={"application_id": application_id,
              # authorization_id intentionally NOT emitted — it appears in the
              # forbidden-key set. Only the application id is safe.
              "url": "/approvals"},
        dedup_key=f"authexp:{authorization_id}",
    )


async def on_support_ticket_replied(user_id: str, ticket_id: str) -> None:
    await _safe_dispatch(
        user_id, "support",
        data={"ticket_id": ticket_id, "url": "/settings"},
        dedup_key=f"ticket:{ticket_id}",
    )

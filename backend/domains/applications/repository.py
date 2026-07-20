"""Applications repository — atomic state transitions only.

Founder Directive #4 (compensating requirement for Mongo deviation):
Every state transition uses atomic find_one_and_update with an expected-state precondition.
No read-modify-write; no race window. If the current DB state doesn't match `expected_state`,
the update NEVER runs.

Allowed state graph (matches Phase 5 tracker spec):
  shortlisted -> preparing -> awaiting_approval -> approved -> submitting -> submitted
     |               |                                                          |
     +---------------+---> closed                                                +--> response -> interview -> offer
"""
from __future__ import annotations
from typing import Any
from pymongo import ReturnDocument
from core.db import get_db
from core.time_utils import utc_now

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "shortlisted": {"preparing", "closed"},
    "preparing": {"awaiting_approval", "closed"},
    "awaiting_approval": {"approved", "preparing", "closed"},
    "approved": {"submitting", "closed"},
    "submitting": {"submitted", "closed"},
    "submitted": {"response", "closed"},
    "response": {"interview", "closed"},
    "interview": {"offer", "closed"},
    "offer": {"closed"},
    "closed": set(),
}


class InvalidTransition(Exception):
    def __init__(self, from_state: str, to_state: str):
        super().__init__(f"invalid_transition:{from_state}->{to_state}")
        self.from_state = from_state
        self.to_state = to_state


async def atomic_transition(
    *,
    user_id: str,
    application_id: str,
    expected_state: str,
    new_state: str,
    extra_set: dict[str, Any] | None = None,
) -> dict | None:
    """Atomic transition. Returns updated doc, or None if precondition failed."""
    allowed = ALLOWED_TRANSITIONS.get(expected_state, set())
    if new_state not in allowed:
        raise InvalidTransition(expected_state, new_state)
    set_payload: dict[str, Any] = {"state": new_state, "updated_at": utc_now()}
    if extra_set:
        set_payload.update(extra_set)
    updated = await get_db().applications.find_one_and_update(
        {"id": application_id, "user_id": user_id, "state": expected_state},
        {"$set": set_payload},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )
    return updated


async def by_id(application_id: str, user_id: str) -> dict | None:
    return await get_db().applications.find_one({"id": application_id, "user_id": user_id}, {"_id": 0})

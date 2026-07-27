"""Self-healing — Phase 5.4 (Founder Directive 2026-07-28).

RULE:
  Fill confidence below threshold → assisted lane.
  Silent failure forbidden; wrong submission forbidden; every downgrade
  logged with a NAMED reason.

Public API:
  * threshold_check(form_map, threshold=0.7) → bool
  * downgrade_map_to_assisted(ats, fingerprint, reason) → dict
  * route_application_to_assisted(application_id, user_id, reason) → dict
  * log_silent_failure(source, context) → dict         # always audit
  * log_wrong_submission(source, context) → dict        # always audit
  * assisted_lane_reason(application_id) → dict | None  # for UI

Storage:
  * `self_healing_events` — one row per downgrade/failure event.
  * `applications.state = "assisted"` and `applications.assisted_reason`
    when a specific application is downgraded.

This module composes `form_map_cache.demote` and does NOT reimplement
the demote logic — it wraps it with the assisted-lane routing rule.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from core import db as core_db
from services import form_map_cache


log = logging.getLogger("self_healing")


# Confidence threshold — below this, we don't trust the form-map cache
# for this fingerprint and route the fill to assisted lane. Env-tunable
# so ops can raise the bar without a code change.
import os as _os
CONFIDENCE_THRESHOLD = float(_os.environ.get(
    "SELF_HEALING_CONFIDENCE_THRESHOLD", "0.7"))


# Event kinds — stable audit vocabulary.
EVENT_MAP_DEMOTED_LOW_CONFIDENCE = "map_demoted_low_confidence"
EVENT_MAP_DEMOTED_FINGERPRINT_DRIFT = "map_demoted_fingerprint_drift"
EVENT_APP_ROUTED_ASSISTED = "app_routed_assisted"
EVENT_SILENT_FAILURE = "silent_failure"
EVENT_WRONG_SUBMISSION = "wrong_submission"


def threshold_check(form_map: dict | None,
                     threshold: float | None = None) -> bool:
    """True if the map is trustworthy at the given threshold. A None or
    demoted map fails the check."""
    if not form_map:
        return False
    if form_map.get("status") != form_map_cache.STATUS_VERIFIED:
        return False
    threshold = threshold if threshold is not None else CONFIDENCE_THRESHOLD
    return float(form_map.get("fill_confidence") or 0.0) >= threshold


async def _log_event(kind: str, *, source: str, context: dict) -> dict:
    doc = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "source": source,
        "context": dict(context),
        "at": datetime.now(timezone.utc),
    }
    try:
        await core_db.get_db().self_healing_events.insert_one(dict(doc))
    except Exception:
        log.warning("self_healing: event insert failed", exc_info=True)
    return doc


async def downgrade_map_to_assisted(*, ats: str, fingerprint: str,
                                       reason: str,
                                       source: str = "self_healing",
                                       ) -> dict:
    """Wrap `form_map_cache.demote` with an audit event. Callers ensure
    subsequent dispatches route to the assisted lane by calling
    `route_application_to_assisted` on impacted applications, OR by
    checking `threshold_check(lookup(...))` in the dispatch chokepoint."""
    demoted = await form_map_cache.demote(ats, fingerprint, reason=reason)
    kind = (EVENT_MAP_DEMOTED_FINGERPRINT_DRIFT
             if "drift" in reason.lower() else EVENT_MAP_DEMOTED_LOW_CONFIDENCE)
    await _log_event(kind, source=source,
                       context={"ats": ats, "fingerprint": fingerprint,
                                "reason": reason,
                                "previous_confidence": (demoted or {})
                                    .get("demote_events", [{}])[-1]
                                    .get("previous_confidence")})
    return demoted or {}


async def route_application_to_assisted(*, application_id: str, user_id: str,
                                            reason: str,
                                            source: str = "self_healing",
                                            ) -> dict:
    """Move a specific application to the assisted lane. Sets
    `applications.state = "assisted"` and stores the named reason so
    the UI can render "Why is this in assisted lane?"."""
    now = datetime.now(timezone.utc)
    db = core_db.get_db()
    await db.applications.update_one(
        {"id": application_id, "user_id": user_id},
        {"$set": {"state": "assisted",
                    "assisted_reason": reason,
                    "assisted_at": now,
                    "updated_at": now}},
    )
    return await _log_event(EVENT_APP_ROUTED_ASSISTED, source=source,
                              context={"application_id": application_id,
                                        "user_id": user_id, "reason": reason})


async def log_silent_failure(*, source: str, context: dict) -> dict:
    """Silent failure is FORBIDDEN — any code path that would swallow
    an error MUST call this. The audit row is what makes the failure
    not-silent."""
    return await _log_event(EVENT_SILENT_FAILURE, source=source,
                              context=context)


async def log_wrong_submission(*, source: str, context: dict) -> dict:
    """Wrong submission is FORBIDDEN — this exists so that a validator
    or dispatch chokepoint can PROVE a wrong submission was caught,
    while surfacing enough context that the review-lane UI can show it."""
    return await _log_event(EVENT_WRONG_SUBMISSION, source=source,
                              context=context)


async def assisted_lane_reason(application_id: str) -> dict | None:
    """Fetch the most recent assisted-lane reason for an application —
    powers the UI copy "Why is this in assisted lane?"."""
    db = core_db.get_db()
    app = await db.applications.find_one(
        {"id": application_id},
        {"_id": 0, "state": 1, "assisted_reason": 1, "assisted_at": 1},
    )
    if not app or app.get("state") != "assisted":
        return None
    return {"reason": app.get("assisted_reason"),
             "at": app.get("assisted_at")}

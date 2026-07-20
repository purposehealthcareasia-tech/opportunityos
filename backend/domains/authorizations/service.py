"""authorizations — per-application authorization scopes for submission.

Data model (`authorization_scopes` collection):
  { id, user_id, kind ("application_submission"), target (application_id),
    materials_hash (sha256 of the packet at approval time),
    expires_at (utc datetime, +72h from creation),
    revoked_at (utc datetime | None),
    consent_ref (id of latest track_applications consent row at approval time),
    created_at, updated_at }

Rule: submit-time requires an authorization that is present, unexpired, unrevoked, AND
materials_hash still matches the CURRENT accepted materials for the application. If the
user edited resume lines or screener answers after approval, the hash mismatches and the
submit path returns 409 "materials changed — re-approval required".
"""
from __future__ import annotations
import uuid
from datetime import timedelta
from typing import Any
from core.db import get_db
from core.time_utils import utc_now


APPLICATION_SUBMISSION = "application_submission"
AUTH_TTL_HOURS = 72


async def create(
    *,
    user_id: str,
    application_id: str,
    materials_hash: str,
    consent_ref: str | None,
) -> dict[str, Any]:
    """Insert a new authorization row. Multiple auths per application are allowed —
    e.g. after a revoke + re-approve, both rows remain; the effective one is the latest
    non-revoked row with the current materials_hash.
    """
    now = utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "kind": APPLICATION_SUBMISSION,
        "target": application_id,
        "materials_hash": materials_hash,
        "expires_at": now + timedelta(hours=AUTH_TTL_HOURS),
        "revoked_at": None,
        "consent_ref": consent_ref,
        "created_at": now,
        "updated_at": now,
    }
    await get_db().authorization_scopes.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def latest_for_application(user_id: str, application_id: str) -> dict | None:
    """Return the most recent authorization row (any status) for this application."""
    return await get_db().authorization_scopes.find_one(
        {"user_id": user_id, "kind": APPLICATION_SUBMISSION, "target": application_id},
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def revoke_latest(user_id: str, application_id: str) -> dict | None:
    """Revoke the latest non-revoked authorization. Returns the updated row or None if none."""
    now = utc_now()
    return await get_db().authorization_scopes.find_one_and_update(
        {
            "user_id": user_id,
            "kind": APPLICATION_SUBMISSION,
            "target": application_id,
            "revoked_at": None,
        },
        {"$set": {"revoked_at": now, "updated_at": now}},
        projection={"_id": 0},
        sort=[("created_at", -1)],
        return_document=True,  # pymongo.ReturnDocument.AFTER == True
    )


def is_valid(auth: dict | None, *, current_hash: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok=True."""
    if not auth:
        return False, "no_authorization"
    if auth.get("revoked_at"):
        return False, "authorization_revoked"
    exp = auth.get("expires_at")
    if exp is None:
        return False, "authorization_no_expiry"
    now = utc_now()
    if not hasattr(exp, "tzinfo"):
        return False, "authorization_malformed"
    # Motor returns UTC datetimes as naive; normalize to timezone-aware for a fair comparison.
    if exp.tzinfo is None:
        from datetime import timezone as _tz
        exp = exp.replace(tzinfo=_tz.utc)
    if exp <= now:
        return False, "authorization_expired"
    if auth.get("materials_hash") != current_hash:
        return False, "materials_changed"
    return True, ""

"""Phase 3 · SUPPLY ENGINE — self-serve URL ingestion + voting queue.

Three endpoints (all writes are consent-gated / role-gated):

  POST /api/v1/employers/connect        — user submits an employer URL
                                          for the founder to consider
                                          adding to the discovery lane
  POST /api/v1/employers/vote           — user upvotes an already-suggested
                                          employer key
  GET  /api/v1/admin/employers/queue    — ADMIN-ONLY ranked queue by votes

Data model
----------
`employer_submissions` (append-only):
  {
    "id": uuid, "user_id": str,
    "submitted_url": str,          # verbatim, HTTPS
    "canonical_host": str,         # lowercased, no www., no trailing slash
    "employer_key": str,           # same as canonical_host — join key
    "submitted_at": datetime,
    "status": "pending" | "verified" | "rejected",
    "reject_reason": str | null,
    "notes": str | null,           # optional user-supplied
  }

`employer_votes` (upsert unique on `(user_id, employer_key)`):
  {
    "id": uuid, "user_id": str,
    "employer_key": str,           # canonical_host of submission
    "voted_at": datetime,
  }

Rails
-----
- HTTPS URLs only (mirror of the booking_url rail from Phase 1 §1c).
- Host must be an FQDN with a dot, ≤ 253 chars, no user@ / port / query.
- Rate limit: at most 20 submissions per user per 24h (protects against
  spam from a compromised account without blocking legitimate research).
- One vote per user per employer_key (upsert semantics).
- The `verified` flip and the `rejected` flip are ADMIN-ONLY operations
  and are NOT exposed on this router (they're written by the admin
  triage tool, out of scope for Phase 3 initial surface).
"""
from __future__ import annotations
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from core.db import get_db
from core.deps import get_current_user, require_role
from core.time_utils import utc_now
from domains.audit import service as audit


router = APIRouter(prefix="/api/v1", tags=["supply"])


# ----------------------------------------------------------------------
# Validation helpers
# ----------------------------------------------------------------------

_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_MAX_URL_LEN = 500
_MAX_NOTES_LEN = 500
_MAX_SUBMISSIONS_PER_24H = 20


def canonicalize_host(url: str) -> str:
    """Strict URL → canonical host. Raises HTTPException(422) on any
    schema violation. The output form is used as the join key for the
    `employer_votes` collection, so two users submitting different-cased
    or www./bare variants of the same brand collapse to one queue row."""
    if not url or len(url) > _MAX_URL_LEN:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_url", "message":
                    f"URL must be non-empty and ≤ {_MAX_URL_LEN} chars."})
    if not url.lower().startswith("https://"):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_url",
                    "message": "must be an https:// URL"})
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=422,
                              detail={"error": "invalid_url",
                                       "message": "URL failed to parse"})
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422,
                              detail={"error": "invalid_url",
                                       "message": "URL must not include userinfo"})
    if parsed.query or parsed.fragment:
        raise HTTPException(status_code=422,
                              detail={"error": "invalid_url",
                                       "message":
                                       "URL must not include query or fragment"})
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not _HOST_RE.match(host):
        raise HTTPException(status_code=422,
                              detail={"error": "invalid_url",
                                       "message":
                                       "host must be a valid public FQDN"})
    return host


# ----------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------

class ConnectRequest(BaseModel):
    url: str = Field(..., description="Employer careers page URL, https:// required")
    notes: Optional[str] = Field(default=None, max_length=_MAX_NOTES_LEN)


class VoteRequest(BaseModel):
    employer_key: str = Field(..., description="Canonical host from a prior /connect")

    @field_validator("employer_key")
    @classmethod
    def _validate(cls, v: str) -> str:
        if not _HOST_RE.match(v.lower()):
            raise ValueError("employer_key must be a canonical host")
        return v.lower()


# ----------------------------------------------------------------------
# 1 · /employers/connect
# ----------------------------------------------------------------------

@router.post("/employers/connect")
async def connect_employer(
    req: ConnectRequest,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Submit an employer URL for founder triage. Returns 201 on new
    submission, 200 with `already_submitted` on a duplicate for the
    same user."""
    canonical = canonicalize_host(req.url)
    db = get_db()

    # 24h rate limit — count is user-scoped, cheap query.
    since = utc_now() - timedelta(hours=24)
    recent_count = await db.employer_submissions.count_documents({
        "user_id": user["id"], "submitted_at": {"$gte": since},
    })
    if recent_count >= _MAX_SUBMISSIONS_PER_24H:
        raise HTTPException(
            status_code=429,
            detail={"error": "submission_rate_limit",
                     "message": (f"You've submitted {recent_count} employers "
                                  f"in the last 24h; the cap is "
                                  f"{_MAX_SUBMISSIONS_PER_24H} per user.")})

    # Dedup: same user + same canonical host = idempotent 200.
    existing = await db.employer_submissions.find_one(
        {"user_id": user["id"], "canonical_host": canonical},
        {"_id": 0},
    )
    if existing:
        response.status_code = 200
        return {"submission": existing, "already_submitted": True}

    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "submitted_url": req.url,
        "canonical_host": canonical,
        "employer_key": canonical,
        "submitted_at": utc_now(),
        "status": "pending",
        "reject_reason": None,
        "notes": (req.notes or None),
    }
    await db.employer_submissions.insert_one(row)
    await audit.write(user["id"], "supply.connect_submitted",
                       f"employer:{canonical}",
                       {"submission_id": row["id"]})
    row.pop("_id", None)
    response.status_code = 201
    return {"submission": row, "already_submitted": False}


# ----------------------------------------------------------------------
# 2 · /employers/vote
# ----------------------------------------------------------------------

@router.post("/employers/vote")
async def vote_employer(
    req: VoteRequest,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """One vote per (user, employer_key) — upsert semantics; a second
    call returns 200 + `already_voted: true`."""
    db = get_db()
    existing = await db.employer_votes.find_one(
        {"user_id": user["id"], "employer_key": req.employer_key},
        {"_id": 0},
    )
    if existing:
        response.status_code = 200
        return {"vote": existing, "already_voted": True}
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "employer_key": req.employer_key,
        "voted_at": utc_now(),
    }
    await db.employer_votes.insert_one(row)
    await audit.write(user["id"], "supply.vote",
                       f"employer:{req.employer_key}",
                       {"vote_id": row["id"]})
    row.pop("_id", None)
    response.status_code = 201
    return {"vote": row, "already_voted": False}


# ----------------------------------------------------------------------
# 3 · /admin/employers/queue  (ADMIN-ONLY)
# ----------------------------------------------------------------------

@router.get("/admin/employers/queue")
async def admin_queue(
    limit: int = 50,
    user: dict = Depends(require_role("admin")),
):
    """Ranked queue by vote count desc, then by earliest submission time
    (older submissions ahead of newer ones at equal vote count).
    Read-only. Never mutates state."""
    db = get_db()
    if limit < 1 or limit > 200:
        limit = 50

    # Aggregate vote count per employer_key across the votes collection.
    pipeline = [
        {"$group": {"_id": "$employer_key", "votes": {"$sum": 1}}},
        {"$sort": {"votes": -1, "_id": 1}},
        {"$limit": limit},
    ]
    vote_rows = await db.employer_votes.aggregate(pipeline).to_list(limit)
    vote_map = {r["_id"]: r["votes"] for r in vote_rows}

    # Pull the *pending* submissions we care about; include every key
    # that has votes even if there's no matching submission yet.
    keys_from_votes = set(vote_map.keys())
    keys_from_subs: set[str] = set()

    # Read every pending submission (bounded by limit×3 for safety).
    subs: list[dict] = []
    async for s in db.employer_submissions.find(
        {"status": "pending"},
        {"_id": 0, "canonical_host": 1, "submitted_at": 1,
          "submitted_url": 1, "id": 1},
    ).sort("submitted_at", 1).limit(limit * 3):
        keys_from_subs.add(s["canonical_host"])
        subs.append(s)

    # Build queue rows.
    queue: list[dict] = []
    for key in keys_from_votes | keys_from_subs:
        matching = [s for s in subs if s["canonical_host"] == key]
        row = {
            "employer_key": key,
            "votes": vote_map.get(key, 0),
            "submission_count": len(matching),
            "earliest_submitted_at": (
                min(s["submitted_at"] for s in matching).isoformat()
                if matching else None
            ),
            "example_url": matching[0]["submitted_url"] if matching else None,
        }
        queue.append(row)

    # Rank: votes desc, then earliest submission asc, then key asc.
    def _sort_key(r):
        return (
            -r["votes"],
            r["earliest_submitted_at"] or "9999",
            r["employer_key"],
        )
    queue.sort(key=_sort_key)
    return {"queue": queue[:limit], "total_keys": len(queue)}

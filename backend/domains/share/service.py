"""Phase 5a · Passport Share Link — endpoints + service.

See `domains/share/__init__.py` for rails.

Endpoints (all under `/api/v1/share`):
  POST   /passport                  create link (auth + share_passport consent)
  GET    /passport                  list my links (auth)
  DELETE /passport/{share_id}       revoke a link (auth)
  GET    /p/{share_id}?t={sig}      PUBLIC filtered view (no auth)
  GET    /passport/{share_id}/views my view receipts (auth)
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import get_current_user, require_consent
from core.time_utils import utc_now
from domains.claims.schema import (
    _year_from_iso_month,
    approved_for_user_query,
    claim_type,
    claim_value,
)
from domains.exports.ghosting import _signing_key  # reuse HMAC key (same rails)


router = APIRouter(prefix="/api/v1/share", tags=["share"])


# Scope filters — never surface sealed claims, ITAR flags, salary, or
# preferences under ANY scope. Values are lists of Passport top-level
# keys visible in the response.
_SCOPES = {
    "minimum":  {"name"},
    "moderate": {"name", "education", "us_work_authorized"},
    "full":     {"name", "education", "us_work_authorized",
                 "employment_history", "top_skills"},
}

_MIN_TTL_HOURS = 1
_MAX_TTL_HOURS = 30 * 24   # 30 days hard cap


# --------------------------------------------------------- signing
def _sign_share(share_id: str, user_id: str, scope: str, expires_at: str) -> str:
    """HMAC-SHA256 over the canonical share tuple. The signature travels
    on the URL as `?t=`; the server recomputes and compares."""
    msg = f"{share_id}|{user_id}|{scope}|{expires_at}".encode("utf-8")
    return hmac.new(_signing_key(), msg, hashlib.sha256).hexdigest()


def _hash_ua(ua: str) -> str:
    """SHA-256 of the User-Agent — stored as a short hash for
    receipt-level attribution without carrying the raw UA."""
    return hashlib.sha256((ua or "").encode("utf-8")).hexdigest()[:16]


def _redact_ip(ip: str) -> str:
    """Redact to /24 network for IPv4, /48 for IPv6. Never store the
    full IP — receipts show a coarse network fragment only."""
    try:
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv4Address):
            return str(ipaddress.ip_network(f"{ip}/24", strict=False))
        return str(ipaddress.ip_network(f"{ip}/48", strict=False))
    except Exception:
        return "unknown"


# --------------------------------------------------------- filter
async def _load_filtered_passport(user_id: str, scope: str) -> dict:
    """Read the Passport for `user_id` and return only the fields the
    scope permits. Sealed claims + ITAR flags + preferences + salary
    are ALWAYS excluded. Missing fields become empty strings/lists
    (never null) so the public view has a stable shape."""
    if scope not in _SCOPES:
        raise HTTPException(status_code=400, detail="bad_scope")
    db = get_db()
    profile = await db.users.find_one({"id": user_id}, {"name": 1, "_id": 0})
    # Canonical approved-claims read (single source of truth in
    # domains/claims/schema.py — prevents the schema-drift class of
    # bug that hit Phase 5 Gate C · FIX 1).
    claims_cursor = db.claims.find(approved_for_user_query(user_id))
    claims = [c async for c in claims_cursor]

    allow = _SCOPES[scope]
    view: dict = {"name": "" if "name" not in allow else (profile or {}).get("name") or ""}

    if "education" in allow:
        # Public-API keys ("school", "graduation_year") are stable — they
        # were published in PHASE-5-EVIDENCE.md. We source them from the
        # ACTUAL value sub-doc keys ("institution", "end") via the
        # schema accessor + year parser (Gate C · FIX 1B).
        edu_list = []
        for c in claims:
            if claim_type(c) != "education":
                continue
            v = claim_value(c)
            edu_list.append({
                "school": v.get("institution", ""),
                "degree": v.get("degree", ""),
                "field":  v.get("field", ""),
                "graduation_year": _year_from_iso_month(v.get("end")),
            })
        view["education"] = edu_list

    if "us_work_authorized" in allow:
        # Boolean only. Never the visa status literal (ITAR-adjacent).
        eprofile = await db.eligibility_profiles.find_one({"user_id": user_id})
        status_val = (eprofile or {}).get("status")
        view["us_work_authorized"] = (
            None if not status_val else status_val in {"us_citizen", "us_permanent_resident"}
        )

    if "employment_history" in allow:
        # Same published-key stability: "title"/"start_year"/"end_year"
        # sourced from actual value keys "role"/"start"/"end".
        emps = []
        for c in claims:
            if claim_type(c) != "employment":
                continue
            v = claim_value(c)
            emps.append({
                "title": v.get("role", "") or v.get("title", ""),
                "company": v.get("company", ""),
                "start_year": _year_from_iso_month(v.get("start")),
                "end_year": _year_from_iso_month(v.get("end")),
            })
        view["employment_history"] = emps

    if "top_skills" in allow:
        skills = [
            (claim_value(c).get("name") or "").strip()
            for c in claims if claim_type(c) == "skill"
        ]
        view["top_skills"] = [s for s in skills if s][:5]

    return view


# --------------------------------------------------------- schemas
class CreateShareRequest(BaseModel):
    scope: str = Field(..., description="minimum | moderate | full")
    ttl_hours: int = Field(..., ge=_MIN_TTL_HOURS, le=_MAX_TTL_HOURS)
    employer_hint: Optional[str] = Field(
        None, max_length=120,
        description="Optional label ('Lucid Motors', 'referral from Priya'). Stored, never shown to viewer.",
    )


# --------------------------------------------------------- endpoints
@router.post("/passport")
async def create_share(
    req: CreateShareRequest,
    user: dict = Depends(require_consent("share_passport")),
):
    if req.scope not in _SCOPES:
        raise HTTPException(status_code=400, detail="bad_scope")

    db = get_db()
    share_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=req.ttl_hours)
    exp_iso = expires_at.isoformat()
    sig = _sign_share(share_id, user["id"], req.scope, exp_iso)

    doc = {
        "id": share_id,
        "user_id": user["id"],
        "scope": req.scope,
        "employer_hint": req.employer_hint or "",
        "created_at": now.isoformat(),
        "expires_at": exp_iso,
        "revoked_at": None,
        "view_count": 0,
        "signature_prefix": sig[:8],   # for debugging; full sig never stored
    }
    await db.passport_shares.insert_one(doc)

    base = os.environ.get("PUBLIC_APP_URL") or ""  # optional; frontend can also build the URL
    public_path = f"/api/v1/share/p/{share_id}?t={sig}"
    return {
        "share_id": share_id,
        "public_path": public_path,
        "public_url": (base.rstrip("/") + public_path) if base else public_path,
        "expires_at": exp_iso,
        "scope": req.scope,
        "revocable": True,
        "receipted": True,
    }


@router.get("/passport")
async def list_shares(user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.passport_shares.find({"user_id": user["id"]}).sort("created_at", -1).limit(200)
    rows = []
    async for d in cursor:
        d.pop("_id", None)
        rows.append(d)
    return {"shares": rows, "count": len(rows)}


@router.delete("/passport/{share_id}")
async def revoke_share(
    share_id: str = Path(..., min_length=8, max_length=64),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    r = await db.passport_shares.update_one(
        {"id": share_id, "user_id": user["id"], "revoked_at": None},
        {"$set": {"revoked_at": now_iso}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="share_not_found_or_already_revoked")
    return {"revoked": True, "share_id": share_id, "revoked_at": now_iso}


@router.get("/passport/{share_id}/views")
async def list_views(
    share_id: str = Path(..., min_length=8, max_length=64),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    share = await db.passport_shares.find_one({"id": share_id, "user_id": user["id"]})
    if not share:
        raise HTTPException(status_code=404, detail="share_not_found")
    cursor = db.share_view_receipts.find({"share_id": share_id}).sort("at", -1).limit(500)
    rows = []
    async for d in cursor:
        d.pop("_id", None)
        rows.append(d)
    return {"share_id": share_id, "view_receipts": rows, "count": len(rows)}


@router.get("/p/{share_id}")
async def public_view(
    request: Request,
    share_id: str = Path(..., min_length=8, max_length=64),
    t: str = Query(..., min_length=32, max_length=128, description="HMAC signature"),
):
    """Public, unauthenticated read. Validates the signature, checks
    expiration + revocation, filters per scope, receipts the view."""
    db = get_db()
    share = await db.passport_shares.find_one({"id": share_id})
    if not share:
        raise HTTPException(status_code=404, detail="share_not_found")

    # Revocation is enforced BEFORE signature check so a compromised
    # link stops working the moment the owner clicks revoke.
    if share.get("revoked_at"):
        raise HTTPException(status_code=410, detail="share_revoked")

    # Expiration.
    try:
        exp = datetime.fromisoformat(share["expires_at"])
    except Exception:
        raise HTTPException(status_code=410, detail="share_expired_malformed")
    if datetime.now(timezone.utc) >= exp:
        raise HTTPException(status_code=410, detail="share_expired")

    # Constant-time signature comparison.
    expected = _sign_share(share_id, share["user_id"], share["scope"], share["expires_at"])
    if not hmac.compare_digest(expected, t):
        raise HTTPException(status_code=403, detail="bad_signature")

    filtered = await _load_filtered_passport(share["user_id"], share["scope"])

    # Receipt the view. Never store raw IP or raw UA.
    view_id = str(uuid.uuid4())
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )
    ua = request.headers.get("user-agent", "")
    await db.share_view_receipts.insert_one({
        "id": view_id,
        "share_id": share_id,
        "user_id": share["user_id"],
        "ip_network": _redact_ip(client_ip),
        "ua_hash": _hash_ua(ua),
        "at": datetime.now(timezone.utc).isoformat(),
    })
    await db.passport_shares.update_one(
        {"id": share_id},
        {"$inc": {"view_count": 1},
         "$set": {"last_viewed_at": datetime.now(timezone.utc).isoformat()}},
    )

    return {
        "share_id": share_id,
        "scope": share["scope"],
        "expires_at": share["expires_at"],
        "passport": filtered,
        "notice": (
            "Read-only Passport view. The Passport owner approved every "
            "claim below and can revoke this link at any time. No résumé "
            "was uploaded. Every view is receipted."
        ),
    }

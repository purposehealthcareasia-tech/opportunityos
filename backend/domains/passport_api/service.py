"""Phase 5i · Passport-as-API v1.

Consent-scoped, per-scope tokens (hash-stored). Every access receipted.
Revocation honored immediately.

Design (SPEC BEFORE BUILD, mirrored in PHASE-5-EVIDENCE.md §5i):
  * Token is a URL-safe random 43-char string (~256 bits of entropy).
  * ONLY a SHA-256 hash is stored server-side; the plain token is
    returned exactly ONCE on mint and never persisted or logged.
  * Each token grants access to ONE scope subset (a subset of the
    same _SCOPES map used by 5a Share Link — reuse for consistency).
  * Access endpoint validates via Authorization: Bearer header.
  * Every access appends a row to `passport_api_receipts`.
  * Revocation is an immediate DB mutation; subsequent requests 401.
"""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import require_consent
from domains.share.service import _SCOPES, _load_filtered_passport


router = APIRouter(prefix="/api/v1/passport-api", tags=["passport_api"])


_MIN_TTL_HOURS = 1
_MAX_TTL_HOURS = 30 * 24


def _hash_token(t: str) -> str:
    return hashlib.sha256((t or "").encode("utf-8")).hexdigest()


def _redact_ip(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv4Address):
            return str(ipaddress.ip_network(f"{ip}/24", strict=False))
        return str(ipaddress.ip_network(f"{ip}/48", strict=False))
    except Exception:
        return "unknown"


class MintTokenRequest(BaseModel):
    scope: str = Field(..., description="minimum | moderate | full")
    ttl_hours: int = Field(..., ge=_MIN_TTL_HOURS, le=_MAX_TTL_HOURS)
    audience_label: Optional[str] = Field(
        None, max_length=80,
        description="Free-text label for who you're minting this for ('Acme HR verifier'). Never shown to token holder.",
    )


@router.post("/tokens/mint")
async def mint_token(
    req: MintTokenRequest,
    user: dict = Depends(require_consent("passport_api_access")),
):
    if req.scope not in _SCOPES:
        raise HTTPException(status_code=400, detail="bad_scope")
    db = get_db()
    tok = secrets.token_urlsafe(32)   # ~43 chars, ~256 bits entropy
    tok_hash = _hash_token(tok)
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=req.ttl_hours)
    row = {
        "id": tid,
        "user_id": user["id"],
        "scope": req.scope,
        "audience_label": (req.audience_label or "")[:80],
        "token_hash": tok_hash,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "revoked_at": None,
        "access_count": 0,
    }
    await db.passport_api_tokens.insert_one(row)
    return {
        # RETURN THE PLAIN TOKEN EXACTLY ONCE. Never persisted server-
        # side; never logged. The caller MUST capture it now.
        "token": tok,
        "token_id": tid,
        "scope": req.scope,
        "expires_at": row["expires_at"],
        "notice": (
            "Store this token securely — it is returned exactly once. "
            "Fynd persists only a SHA-256 hash. You can revoke this "
            "token immediately from /tokens/{token_id}."
        ),
    }


@router.get("/tokens")
async def list_tokens(user: dict = Depends(require_consent("passport_api_access"))):
    db = get_db()
    rows = []
    async for r in db.passport_api_tokens.find({"user_id": user["id"]}) \
            .sort("created_at", -1).limit(500):
        r.pop("_id", None)
        r.pop("token_hash", None)      # never leak the hash
        rows.append(r)
    return {"tokens": rows, "count": len(rows)}


@router.delete("/tokens/{token_id}")
async def revoke_token(
    token_id: str = Path(..., min_length=8, max_length=64),
    user: dict = Depends(require_consent("passport_api_access")),
):
    db = get_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    r = await db.passport_api_tokens.update_one(
        {"id": token_id, "user_id": user["id"], "revoked_at": None},
        {"$set": {"revoked_at": now_iso}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="token_not_found_or_already_revoked")
    return {"revoked": True, "token_id": token_id, "revoked_at": now_iso}


# ------------------------------------------------------------------ access
@router.get("/passport")
async def passport_via_token(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Third-party access. Reads the Bearer token, looks up the hash,
    validates revocation + expiry, filters per scope, receipts."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer")
    tok = authorization.split(" ", 1)[1].strip()
    tok_hash = _hash_token(tok)
    db = get_db()
    row = await db.passport_api_tokens.find_one({"token_hash": tok_hash})
    if not row:
        raise HTTPException(status_code=401, detail="bad_token")
    if row.get("revoked_at"):
        raise HTTPException(status_code=410, detail="token_revoked")
    try:
        exp = datetime.fromisoformat(row["expires_at"])
    except Exception:
        raise HTTPException(status_code=410, detail="token_expired_malformed")
    if datetime.now(timezone.utc) >= exp:
        raise HTTPException(status_code=410, detail="token_expired")

    filtered = await _load_filtered_passport(row["user_id"], row["scope"])

    # Receipt.
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )
    await db.passport_api_receipts.insert_one({
        "id": str(uuid.uuid4()),
        "token_id": row["id"],
        "user_id": row["user_id"],
        "scope": row["scope"],
        "ip_network": _redact_ip(client_ip),
        "at": datetime.now(timezone.utc).isoformat(),
    })
    await db.passport_api_tokens.update_one(
        {"id": row["id"]},
        {"$inc": {"access_count": 1},
         "$set": {"last_accessed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "scope": row["scope"],
        "passport": filtered,
        "notice": (
            "Passport-as-API v1. The Passport owner minted this token "
            "consent-scoped and can revoke it at any time; every access "
            "is receipted."
        ),
    }

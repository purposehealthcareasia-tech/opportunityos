"""Phase 4 · Ghosting evidence export (signed JSON, consent-gated).

Endpoint
--------
GET  /api/v1/exports/ghosting-evidence[?format=json]
POST /api/v1/exports/ghosting-evidence/verify

Fix 5 (2026-08-07) — silent-scope violation SEALED. `?format=pdf`
now returns an EXPLICIT 501 with `pdf_not_available` + a `formats`
capability field. `?format=json` (or no `format` param) returns the
signed JSON manifest.

Fix 6 (2026-08-07) — signature verifiability. `POST .../verify` accepts
a manifest + signature and returns `{valid: true|false}`. No key is
exposed; the endpoint recomputes the HMAC-SHA256 server-side. This
makes signatures cross-verifiable by third parties WITHOUT ever
handing them the signing key.

Contract
--------
Signature = HMAC-SHA256 over canonical JSON serialization of the
manifest body (sort_keys=True, separators=(",",":"), default=str).
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from core.db import get_db
from core.deps import require_consent


router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


GHOSTING_THRESHOLD_DAYS = int(
    os.environ.get("GHOSTING_THRESHOLD_DAYS", "21") or "21"
)


# What formats we ACTUALLY ship right now. Cross-referenced by both the
# GET endpoint (for the 501 branch) and the response capability field
# (so consumers programmatically know what's supported without guessing).
SUPPORTED_FORMATS = ("json",)
PLANNED_FORMATS = ("pdf",)   # documented as not-yet-shipped


def _signing_key() -> bytes:
    """Return the HMAC key. In production, `EVIDENCE_SIGNING_KEY` MUST
    be set to a random ≥32-byte secret. In preview/dev we accept a
    documented placeholder — the signature still self-verifies but
    won't cross-verify with production."""
    key = os.environ.get("EVIDENCE_SIGNING_KEY")
    if key:
        return key.encode("utf-8")
    # Documented dev placeholder — never used in production.
    return b"dev-only-evidence-key-DO-NOT-USE-IN-PROD-2026"


def canonical_serialize(payload: dict) -> bytes:
    """Canonical JSON serialization used for both signing and
    verification. sort_keys=True + no whitespace + default=str for
    datetimes. Locked because a mismatched serializer breaks all
    signature verification."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")


def _sign(payload: dict) -> str:
    return hmac.new(
        _signing_key(), canonical_serialize(payload), hashlib.sha256
    ).hexdigest()


class VerifyRequest(BaseModel):
    manifest: dict
    signature: str


@router.get("/ghosting-evidence")
async def ghosting_evidence(
    format: str = Query("json", description="Response format; `json` only supported today"),
    user: dict = Depends(require_consent("track_applications")),
):
    """Signed evidence bundle of ghosted applications.

    An application is "ghosted" iff:
      1. It was submitted (`state != "draft"`, `created_at` older than
         GHOSTING_THRESHOLD_DAYS).
      2. Zero `outcomes` rows exist for it with `event != "viewed"`.
    """
    # Fix 5 — explicit format handling. Silent scope reduction is a
    # rail violation.
    fmt = (format or "json").lower().strip()
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=501,
            detail={
                "error": "pdf_not_available" if fmt == "pdf" else "format_not_available",
                "message": (
                    f"Format `{fmt}` is not shipped today. Supported: "
                    f"{list(SUPPORTED_FORMATS)}. Planned but not-yet-"
                    f"shipped: {list(PLANNED_FORMATS)}. The JSON bundle "
                    "is the authoritative signed artifact."
                ),
                "capability": {
                    "formats_supported": list(SUPPORTED_FORMATS),
                    "formats_planned": list(PLANNED_FORMATS),
                },
            },
        )

    db = get_db()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=GHOSTING_THRESHOLD_DAYS)

    # 1) Pull candidate applications (submitted, older than cutoff).
    candidates: list[dict] = []
    async for a in db.applications.find(
        {"user_id": user["id"], "state": {"$ne": "draft"},
          "created_at": {"$lt": cutoff}},
        {"_id": 0},
    ):
        candidates.append(a)

    if not candidates:
        body = {
            "user_id": user["id"],
            "generated_at": now.isoformat(),
            "threshold_days": GHOSTING_THRESHOLD_DAYS,
            "count": 0,
            "applications": [],
            "note": (
                f"No submitted applications older than "
                f"{GHOSTING_THRESHOLD_DAYS} days with zero response "
                f"activity. Nothing to attest."
            ),
        }
        return {
            "manifest": body,
            "signature": _sign(body),
            "capability": {
                "formats_supported": list(SUPPORTED_FORMATS),
                "formats_planned": list(PLANNED_FORMATS),
            },
            "verification": {
                "algorithm": "HMAC-SHA256",
                "canonical_serialization": (
                    'json.dumps(manifest, sort_keys=True, '
                    'separators=(",",":"), default=str).encode()'
                ),
                "verify_endpoint": "POST /api/v1/exports/ghosting-evidence/verify",
                "note": (
                    "The verify endpoint recomputes the HMAC server-side "
                    "and returns {valid: true|false} without exposing "
                    "the signing key. Third-party verification without "
                    "the key: send `{manifest, signature}` to the verify "
                    "endpoint."
                ),
            },
        }

    # 2) Filter by "zero non-viewed outcomes".
    ghosted: list[dict] = []
    for a in candidates:
        n = await db.outcomes.count_documents({
            "user_id": user["id"],
            "application_id": a["id"],
            "event": {"$ne": "viewed"},
        })
        if n == 0:
            created = a.get("created_at")
            if isinstance(created, datetime) and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            ghosted.append({
                "application_id": a["id"],
                "job_id": a.get("job_id"),
                "employer": (a.get("employer") or a.get("company_name")),
                "state": a.get("state"),
                "submitted_at": (
                    created.isoformat()
                    if isinstance(created, datetime)
                    else created
                ),
                "days_since_submit": round(
                    (now - created).total_seconds() / 86400.0, 1
                ) if isinstance(created, datetime) else None,
            })

    ghosted.sort(key=lambda r: r["submitted_at"])

    body = {
        "user_id": user["id"],
        "generated_at": now.isoformat(),
        "threshold_days": GHOSTING_THRESHOLD_DAYS,
        "count": len(ghosted),
        "applications": ghosted,
        "note": (
            "Signed evidence bundle. Each entry is a submitted "
            "application with zero non-viewed outcome events after "
            f"{GHOSTING_THRESHOLD_DAYS} days. Manifest is HMAC-SHA256 "
            "signed; the signature covers a canonical JSON serialization "
            "of the manifest body — never fabricated, always ledger-derived."
        ),
    }
    return {
        "manifest": body,
        "signature": _sign(body),
        "capability": {
            "formats_supported": list(SUPPORTED_FORMATS),
            "formats_planned": list(PLANNED_FORMATS),
        },
        "verification": {
            "algorithm": "HMAC-SHA256",
            "canonical_serialization": (
                'json.dumps(manifest, sort_keys=True, '
                'separators=(",",":"), default=str).encode()'
            ),
            "verify_endpoint": "POST /api/v1/exports/ghosting-evidence/verify",
            "note": (
                "The verify endpoint recomputes the HMAC server-side "
                "and returns {valid: true|false} without exposing the "
                "signing key. Third-party verification without the key: "
                "send `{manifest, signature}` to the verify endpoint."
            ),
        },
    }


@router.post("/ghosting-evidence/verify")
async def ghosting_verify(req: VerifyRequest):
    """Fix 6 — third-party signature verification without key exposure.

    Anyone (auditor, partner, curious inspector) can POST a manifest +
    signature and get a binary `valid` answer. The signing key is never
    exposed; the endpoint recomputes HMAC-SHA256 server-side using the
    canonical serialization defined above.

    Not consent-gated — the manifest is either already in the caller's
    hands (they downloaded it earlier under consent) or it's a forgery
    attempt (in which case `valid=false` is the honest answer).
    """
    if not isinstance(req.manifest, dict) or not isinstance(req.signature, str):
        return {"valid": False, "reason": "malformed_input"}
    expected = _sign(req.manifest)
    if hmac.compare_digest(expected.encode(), req.signature.encode()):
        return {
            "valid": True,
            "algorithm": "HMAC-SHA256",
            "note": (
                "Signature matches the canonical serialization of the "
                "manifest under the current EVIDENCE_SIGNING_KEY."
            ),
        }
    return {
        "valid": False,
        "algorithm": "HMAC-SHA256",
        "note": (
            "Signature does not match. Either the manifest was mutated "
            "after signing, the wrong signing key was used, or the "
            "signature was forged."
        ),
    }

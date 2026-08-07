"""Phase 4 · Ghosting evidence export (signed JSON, consent-gated).

Endpoint
--------
GET /api/v1/exports/ghosting-evidence

Returns a signed JSON manifest of every application the user submitted
that has NO response outcome recorded after `GHOSTING_THRESHOLD_DAYS`
(default 21).

The manifest is:
  - Assembled from the immutable `applications` + `outcomes` ledgers.
  - HMAC-SHA256 signed with `EVIDENCE_SIGNING_KEY` env var (or a
    dev-only fallback). The signature covers a canonical JSON
    serialization of the manifest body; the founder can later re-verify
    the integrity of any exported bundle offline.
  - Consent-gated (`track_applications`).
  - READ-ONLY. Does NOT persist a copy of the export.

We do NOT ship a PDF renderer in this phase — the JSON bundle is the
authoritative signed artifact. A future phase can render a PDF that
embeds this signed JSON verbatim.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from core.db import get_db
from core.deps import require_consent


router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


GHOSTING_THRESHOLD_DAYS = int(
    os.environ.get("GHOSTING_THRESHOLD_DAYS", "21") or "21"
)


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


def _sign(payload: dict) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hmac.new(_signing_key(), canonical, hashlib.sha256).hexdigest()


@router.get("/ghosting-evidence")
async def ghosting_evidence(
    user: dict = Depends(require_consent("track_applications")),
):
    """Signed evidence bundle of ghosted applications.

    An application is "ghosted" iff:
      1. It was submitted (`state != "draft"`, `created_at` older than
         GHOSTING_THRESHOLD_DAYS).
      2. Zero `outcomes` rows exist for it with `event != "viewed"`.
    """
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
        return {"manifest": body, "signature": _sign(body)}

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
    return {"manifest": body, "signature": _sign(body)}

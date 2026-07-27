"""Credential-to-Income router (Phase 3).

Public endpoints for the low-barrier credential card:
  GET /api/v1/credentials/catalog       — full list
  GET /api/v1/credentials/unlock-candidates — live count of Lane-B jobs unlocked
                                             per credential (real jobs query)
  GET /api/v1/credentials/{id}          — single credential detail

Consent-gated on `discover_jobs` (same as feed) because the card is a companion
to the Lane B experience. No writes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.deps import require_consent
from domains.credentials import get_catalog, by_id
from services import credential_unlock as unlock_svc


router = APIRouter(prefix="/api/v1/credentials", tags=["credentials"])


@router.get("/catalog")
async def catalog(user: dict = Depends(require_consent("discover_jobs"))):
    """Return the full credential-to-income catalog. Static, no PII."""
    return {"credentials": get_catalog(), "total": len(get_catalog())}


@router.get("/unlock-candidates")
async def unlock_candidates(
    within_mi: Optional[int] = Query(default=None, ge=0, le=500),
    lane: str = Query(default="income_now", pattern="^(career|income_now|all)$"),
    top_k: int = Query(default=3, ge=1, le=9),
    user: dict = Depends(require_consent("discover_jobs")),
):
    """FACT RULES per founder brief (2026-07-27):
      * `live_unlock_count` is a REAL live jobs query — never fabricated.
      * `credential.time_to_credential` and `approx_cost_usd` are indicative
        ranges from the catalog; the UI must render `suggested_next[]` links
        as authoritative sources so the candidate can verify.
    """
    lane_arg = None if lane == "all" else lane
    rows = await unlock_svc.unlock_candidates(within_mi=within_mi,
                                                lane=lane_arg,
                                                top_k=top_k)
    return {"candidates": rows, "query": {"lane": lane, "within_mi": within_mi}}


@router.get("/{cred_id}")
async def get(cred_id: str, user: dict = Depends(require_consent("discover_jobs"))):
    row = by_id(cred_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="credential_not_found")
    return row

"""Credential-to-Income router (Phase 3).

Public endpoints for the low-barrier credential card:
  GET /api/v1/credentials/catalog       — full list
  GET /api/v1/credentials/{id}          — single credential detail

Consent-gated on `discover_jobs` (same as feed) because the card is a companion
to the Lane B experience. No writes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from core.deps import require_consent
from domains.credentials import get_catalog, by_id


router = APIRouter(prefix="/api/v1/credentials", tags=["credentials"])


@router.get("/catalog")
async def catalog(user: dict = Depends(require_consent("discover_jobs"))):
    """Return the full credential-to-income catalog. Static, no PII."""
    return {"credentials": get_catalog(), "total": len(get_catalog())}


@router.get("/{cred_id}")
async def get(cred_id: str, user: dict = Depends(require_consent("discover_jobs"))):
    row = by_id(cred_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="credential_not_found")
    return row

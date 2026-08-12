"""Application-credits public + admin router.

* GET  /api/v1/credits/me                 — display balance (5s cache)
* GET  /api/v1/credits/ledger             — user's own recent ledger rows
* POST /api/v1/admin/credits/grant        — owner/admin grant (audited)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import get_current_user
from domains.audit import service as audit
from domains.credits import service as credits

log = logging.getLogger("oppos.credits.router")

router = APIRouter(prefix="/api/v1", tags=["credits"])


@router.get("/credits/me")
async def credits_me(user: dict = Depends(get_current_user)):
    """Read-side display of the caller's balance. Never used by
    halt/debit logic — those go through `credits.check_and_debit(...)`.
    5-second in-process cache to keep the feed lightweight."""
    snap = await credits.get_balance(user["id"], use_cache=True)
    return snap


@router.get("/credits/ledger")
async def credits_ledger(user: dict = Depends(get_current_user), limit: int = 100):
    """Return the caller's recent credit ledger rows for their own
    audit. Cap at 100 to prevent runaway responses."""
    limit = max(1, min(500, limit))
    rows = await credits.ledger_page(user["id"], limit=limit)
    return {"rows": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Admin grant — owner / admin / support only.
# ---------------------------------------------------------------------------
import os


def _is_admin_or_owner(user: dict) -> bool:
    if not user:
        return False
    if user.get("role") in ("admin", "support"):
        return True
    email = (user.get("email") or "").lower()
    csv = os.environ.get("PRIVATE_AUTOPILOT_OWNER_EMAILS", "")
    owners = {e.strip().lower() for e in csv.split(",") if e.strip()}
    return email in owners


class GrantRequest(BaseModel):
    target_user_id: str = Field(min_length=1, max_length=200)
    amount: int = Field(gt=0, le=100000)
    source: str = Field(min_length=1, max_length=100)


@router.post("/admin/credits/grant", status_code=status.HTTP_201_CREATED)
async def admin_grant(req: GrantRequest, user: dict = Depends(get_current_user)):
    if not _is_admin_or_owner(user):
        raise HTTPException(status_code=403, detail={"error": "admin_or_owner_required"})
    result = await credits.grant(
        user_id=req.target_user_id,
        amount=req.amount,
        source=req.source,
        admin_actor=user.get("email") or user.get("id"),
    )
    await audit.write(user["id"], "credits.admin_grant",
                       f"user:{req.target_user_id}",
                       {"amount": req.amount, "source": req.source,
                        "ledger_id": result.get("ledger_id")})
    return result

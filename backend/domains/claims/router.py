from fastapi import APIRouter, Depends, HTTPException, status
from core.deps import require_consent
from domains.claims.models import CreateClaimRequest, EditClaimRequest, BulkApproveRequest
from domains.claims import service as svc, repository as repo
from domains.users.sealed import serialize_claim

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


@router.get("")
async def list_claims(
    include_history: bool = False,
    user: dict = Depends(require_consent("process_career_data")),
):
    rows = await repo.list_for_user(user["id"], include_history=include_history)
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        c = serialize_claim(r, viewer_id=user["id"])  # owner — sealed values remain readable
        grouped.setdefault(c["type"], []).append(c)
    # Deterministic type order for the UI
    ordered = sorted(grouped.items(), key=lambda kv: kv[0])
    return {"groups": [{"type": t, "claims": cs} for t, cs in ordered]}


@router.post("", status_code=201)
async def create_claim(req: CreateClaimRequest, user: dict = Depends(require_consent("process_career_data"))):
    c = await svc.create_manual(user["id"], ctype=req.type, value=req.value, sensitivity=req.sensitivity)
    return serialize_claim(c, viewer_id=user["id"])


@router.post("/{claim_id}/approve")
async def approve_claim(claim_id: str, user: dict = Depends(require_consent("process_career_data"))):
    c = await svc.approve(user["id"], claim_id)
    return serialize_claim(c, viewer_id=user["id"])


@router.post("/{claim_id}/reject")
async def reject_claim(claim_id: str, user: dict = Depends(require_consent("process_career_data"))):
    c = await svc.reject(user["id"], claim_id)
    return serialize_claim(c, viewer_id=user["id"])


@router.put("/{claim_id}")
async def edit_claim(claim_id: str, req: EditClaimRequest, user: dict = Depends(require_consent("process_career_data"))):
    if not req.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="value_required")
    c = await svc.edit_claim(user["id"], claim_id, new_value=req.value, new_sensitivity=req.sensitivity)
    return serialize_claim(c, viewer_id=user["id"])


@router.post("/bulk-approve")
async def bulk_approve(req: BulkApproveRequest, user: dict = Depends(require_consent("process_career_data"))):
    return await svc.bulk_approve(user["id"], ctype=req.type, ids=req.ids)


@router.post("/attest-all", status_code=201)
async def attest_all(user: dict = Depends(require_consent("process_career_data"))):
    """Phase 6b · Bulk-attest.

    ONE tap to attest every current claim as true. Records a consent
    ledger row with the SHA-256 of the canonicalized claim set so
    "what was attested" is cryptographically pinned. Per-claim
    edit/reject still works alongside (the individual list endpoints
    are unchanged). Unapproved-Passport rule unchanged — nothing
    generates from claims that aren't attested here.
    """
    from core.policy import policy_version
    return await svc.attest_all(
        user["id"],
        policy_text_version=policy_version(),
        source="claims.attest-all",
    )

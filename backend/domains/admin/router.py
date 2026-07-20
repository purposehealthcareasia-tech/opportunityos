from fastapi import APIRouter, Depends
from core.deps import require_role
from core.db import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/feature-flags")
async def list_feature_flags(_viewer: dict = Depends(require_role("admin", "support"))):
    cur = get_db().feature_flags.find({}, {"_id": 0}).sort("key", 1)
    return {"flags": [f async for f in cur]}


@router.get("/health")
async def admin_health(_viewer: dict = Depends(require_role("admin", "support"))):
    return {"ok": True, "phase": 1, "note": "Admin console proper lands in phase 6."}

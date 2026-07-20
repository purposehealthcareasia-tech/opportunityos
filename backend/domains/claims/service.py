import uuid
from fastapi import HTTPException, status
from core.db import get_db
from core.time_utils import utc_now
from domains.claims import repository as repo
from domains.audit import service as audit


async def insert_from_parse(
    *, user_id: str, document_id: str, model_used: str | None, parsed_claims: list[dict]
) -> int:
    """Persist LLM-parsed claims as pending drafts. Never auto-approved."""
    now = utc_now()
    docs: list[dict] = []
    for pc in parsed_claims:
        docs.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "type": pc["type"],
            "value": pc.get("value") or {},
            "source": {
                "kind": "resume_parse",
                "document_id": document_id,
                "model": model_used,
            },
            "evidence": [{"kind": "document", "document_id": document_id}],
            "verification": {"level": 0, "note": "unverified"},
            "confidence": pc.get("confidence"),
            "user_approved": False,
            "status": "pending",
            "sensitivity": "normal",
            "version": 1,
            "superseded_by": None,
            "created_at": now,
        })
    n = await repo.insert_many(docs)
    if n:
        await audit.write(user_id, "claims.ingest_from_parse", f"document:{document_id}", {"count": n, "model": model_used})
    return n


async def create_manual(user_id: str, *, ctype: str, value: dict, sensitivity: str = "normal") -> dict:
    now = utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "type": ctype,
        "value": value,
        "source": {"kind": "user_provided"},
        "evidence": [],
        "verification": {"level": 0, "note": "unverified"},
        "confidence": None,
        "user_approved": True,       # user is authoring — implicit approval
        "status": "approved",
        "sensitivity": sensitivity,
        "version": 1,
        "superseded_by": None,
        "created_at": now,
    }
    await repo.insert_one(doc)
    await audit.write(user_id, "claim.create_manual", f"claim:{doc['id']}", {"type": ctype})
    return doc


async def approve(user_id: str, claim_id: str) -> dict:
    c = await repo.by_id_for_user(claim_id, user_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="claim_not_found")
    if c.get("superseded_by"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="claim_superseded")
    await repo.update_fields(claim_id, {"status": "approved", "user_approved": True})
    await audit.write(user_id, "claim.approve", f"claim:{claim_id}", {"type": c["type"]})
    fresh = await repo.by_id_for_user(claim_id, user_id)
    return fresh


async def reject(user_id: str, claim_id: str) -> dict:
    c = await repo.by_id_for_user(claim_id, user_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="claim_not_found")
    if c.get("superseded_by"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="claim_superseded")
    await repo.update_fields(claim_id, {"status": "rejected", "user_approved": False})
    await audit.write(user_id, "claim.reject", f"claim:{claim_id}", {"type": c["type"]})
    fresh = await repo.by_id_for_user(claim_id, user_id)
    return fresh


async def edit_claim(user_id: str, claim_id: str, *, new_value: dict, new_sensitivity: str | None) -> dict:
    """Create a new version and set superseded_by on the old one. Original row is NEVER mutated."""
    old = await repo.by_id_for_user(claim_id, user_id)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="claim_not_found")
    if old.get("superseded_by"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="claim_superseded")

    now = utc_now()
    new_id = str(uuid.uuid4())
    new_doc = {
        "id": new_id,
        "user_id": user_id,
        "type": old["type"],
        "value": new_value,
        "source": {
            "kind": "user_edited",
            "from_claim_id": old["id"],
            "from_version": old.get("version", 1),
        },
        "evidence": old.get("evidence", []),
        "verification": old.get("verification", {"level": 0, "note": "unverified"}),
        "confidence": None,
        "user_approved": True,
        "status": "approved",
        "sensitivity": (new_sensitivity if new_sensitivity is not None else old.get("sensitivity", "normal")),
        "version": (old.get("version", 1) or 1) + 1,
        "superseded_by": None,
        "created_at": now,
    }
    await repo.insert_one(new_doc)
    await repo.update_fields(old["id"], {"superseded_by": new_id})
    await audit.write(user_id, "claim.edit", f"claim:{new_id}", {"from": old["id"], "type": old["type"], "new_version": new_doc["version"]})
    return new_doc


async def bulk_approve(user_id: str, *, ctype: str | None, ids: list[str] | None) -> dict:
    if not ctype and not ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="type_or_ids_required")
    if ids:
        target_ids = ids
    else:
        target_ids = await repo.pending_ids(user_id, ctype)
    approved: list[str] = []
    for cid in target_ids:
        c = await repo.by_id_for_user(cid, user_id)
        if not c or c.get("superseded_by") or c.get("status") == "approved":
            continue
        await repo.update_fields(cid, {"status": "approved", "user_approved": True})
        approved.append(cid)
    if approved:
        await audit.write(user_id, "claims.bulk_approve", f"user:{user_id}", {"count": len(approved), "type": ctype})
    return {"approved_count": len(approved), "approved_ids": approved}

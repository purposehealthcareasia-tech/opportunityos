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
    """Persist a user-authored claim as a DRAFT (status='pending', not yet approved).

    Founder Hotfix Gate (2026-08-13): manual entry authors the claim but the
    approve/attestation moment MUST be explicit — the user has to tap
    "Approve" on the Passport row after creating it. `pending` is the same
    status parsed claims use, so they route through the identical approve
    flow (`POST /api/v1/claims/{id}/approve`). See
    `/app/docs/MERGE-PACKET.md` §9.8 for the directive→implementation
    mapping (directive says "draft" → implemented as `pending`; semantic
    equivalence: "awaiting explicit user attestation").
    """
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
        "user_approved": False,      # authoring != attestation — explicit approve required
        "status": "pending",
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


# ---------------------------------------------------------------------------
# Phase 6b · attest-all with claim-set hash.
#
# Approves every pending / not-yet-approved claim in one action AND records
# a cryptographic hash of the exact attested set into the consent ledger.
# The hash is what's pinned — the raw claim rows are stored in `claims`
# and never mutated without a version bump (via `edit_claim` → new row +
# supersedes chain). This means "what you attested to" is provable
# byte-for-byte after the fact.
#
# Called by the /onboarding/launch approve-&-launch screen (Batch C/D).
# Never generates from unattested claims (Passport rule unchanged).
# ---------------------------------------------------------------------------
def _claim_set_hash(claims: list[dict]) -> str:
    """SHA-256 of a canonicalized `[{id, type, value_json, sensitivity}...]`
    list. Sorted by id so ordering never changes the hash. Value dict is
    JSON-canonicalized (sort_keys=True, separators=(',',':') → no whitespace,
    stable key order)."""
    import hashlib
    import json as _json
    canonical = sorted(
        [{
            "id": c["id"],
            "type": c.get("type"),
            "value": _json.loads(_json.dumps(c.get("value") or {},
                                                sort_keys=True, separators=(",", ":"))),
            "sensitivity": c.get("sensitivity") or "normal",
        } for c in claims],
        key=lambda x: x["id"],
    )
    payload = _json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


async def attest_all(
    user_id: str, *,
    policy_text_version: str,
    source: str = "onboarding-launch",
) -> dict:
    """Approve every pending / not-yet-approved claim for this user AND
    write a `claims.attest_all` consent-ledger row containing the
    claim-set hash. Idempotent — a repeat call over the same claim set
    approves nothing new but re-records the current hash (so drift is
    visible in the audit trail)."""
    from domains.consent import repository as consent_repo
    rows = await repo.list_for_user(user_id, include_history=False)
    if not rows:
        return {"attested_count": 0, "claim_set_hash": None,
                "consent_row_id": None, "message": "no_claims_to_attest"}
    approved_ids: list[str] = []
    for c in rows:
        if c.get("superseded_by"):
            continue
        if c.get("status") != "approved" or not c.get("user_approved"):
            await repo.update_fields(c["id"], {"status": "approved", "user_approved": True})
            approved_ids.append(c["id"])
    # Re-read the effective (post-mutation) set for the hash.
    effective = [c for c in await repo.list_for_user(user_id, include_history=False)
                 if not c.get("superseded_by")]
    claim_hash = _claim_set_hash(effective)
    consent_row_id = await consent_repo.append({
        "user_id": user_id,
        "scope": "claims.attest_all",
        "granted": True,
        "policy_text_version": policy_text_version,
        "actor": user_id,
        "source": source,
        "attestation_hash": claim_hash,
        "attested_count": len(effective),
        "newly_approved": len(approved_ids),
    })
    await audit.write(user_id, "claims.attest_all", f"user:{user_id}", {
        "attested_count": len(effective),
        "newly_approved": len(approved_ids),
        "attestation_hash": claim_hash,
        "consent_row_id": consent_row_id,
    })
    return {
        "attested_count": len(effective),
        "newly_approved": len(approved_ids),
        "newly_approved_ids": approved_ids,
        "claim_set_hash": claim_hash,
        "consent_row_id": consent_row_id,
    }

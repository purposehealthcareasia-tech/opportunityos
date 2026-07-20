"""Submission Receipts — Founder Directive #2 contract lands NOW, submit path lands Phase 5.

Contract:
- One row per successfully submitted application. Unique on (user_id, company_id, req_ref).
- APP-LAYER IMMUTABILITY: no `update()` or `delete()` function exists in this module. Ever.
  A correction is a new row with `supersedes` pointing at the original — mirrors the claims
  supersede-by chain. Reviewers audit history by walking the chain, not by mutating rows.
- The insert path is intentionally the ONLY write path exposed. Callers hand in a fully-shaped
  receipt and either see it accepted or a DuplicateReceipt raised by Mongo's unique index.

Phase 3 exposes NO HTTP surface for receipts — the collection exists, the index is proven, and
the write helper is unit-testable. Phase 5's submit flow will call `insert()` post-submit.
"""
from __future__ import annotations
import uuid
from typing import Any
from pymongo.errors import DuplicateKeyError
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit


class DuplicateReceipt(Exception):
    """Raised when a receipt with the same (user_id, company_id, req_ref) already exists."""


async def insert(
    *,
    user_id: str,
    company_id: str,
    req_ref: str,
    application_id: str,
    job_id: str,
    materials_manifest_hash: str,
    submit_channel: str,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Append an immutable receipt row.

    Args:
      req_ref: employer-side reference — e.g. an ATS confirmation id, email Message-ID header,
               or a manual-queue confirmation slug. MUST be non-empty and unique per employer.
      supersedes: optional id of a prior receipt this one corrects. Both rows stay in Mongo;
                  callers filter by `supersedes=null` to see the effective latest.
    """
    if not (user_id and company_id and req_ref and application_id and job_id):
        raise ValueError("all_of(user_id, company_id, req_ref, application_id, job_id)_required")
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "company_id": company_id,
        "req_ref": req_ref,
        "application_id": application_id,
        "job_id": job_id,
        "materials_manifest_hash": materials_manifest_hash,
        "submit_channel": submit_channel,
        "supersedes": supersedes,
        "ts": utc_now(),
    }
    try:
        await get_db().submission_receipts.insert_one(doc)
    except DuplicateKeyError as e:
        raise DuplicateReceipt(str(e))
    await audit.write(
        user_id,
        "submission_receipt.insert",
        f"submission_receipt:{doc['id']}",
        {"application_id": application_id, "req_ref": req_ref, "channel": submit_channel},
    )
    doc.pop("_id", None)
    return doc


async def find_effective(*, user_id: str, application_id: str) -> dict | None:
    """Return the latest non-superseded receipt for an application, if any."""
    db = get_db()
    # Latest row (highest ts) that is not itself superseded.
    receipts = await db.submission_receipts.find(
        {"user_id": user_id, "application_id": application_id},
        {"_id": 0},
    ).sort("ts", -1).to_list(length=100)
    superseded_ids = {r.get("supersedes") for r in receipts if r.get("supersedes")}
    for r in receipts:
        if r["id"] not in superseded_ids:
            return r
    return None

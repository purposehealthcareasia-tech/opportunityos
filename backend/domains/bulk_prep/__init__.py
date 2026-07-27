"""Bulk pre-generation with per-line claim provenance and cost per 1,000 lines.

Phase 4 Founder Brief — Item 2.

Endpoint:
  POST /api/v1/prep/bulk-prepare      { application_ids: [...] }

Rails:
  * consent-gated on `generate_materials`
  * fixture-scoped by default: caps at 25 application_ids per request; hard
    fail if any application_id is not owned by the user
  * NEVER submits or sends anything. Only prepares tailored resume drafts with
    validated per-line claim provenance.
  * Cost is measured by summing token usage from ai_generations rows created
    during the batch. All figures are REAL — never fabricated.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import require_consent
from core.db import get_db
from core.time_utils import utc_now
from domains.applications import service as apps_svc
from domains.audit import service as audit


router = APIRouter(prefix="/api/v1/prep", tags=["bulk_prep"])


MAX_BATCH = 25


class BulkPrepareRequest(BaseModel):
    application_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH)


class BulkPrepareItemResult(BaseModel):
    application_id: str
    status: str  # "prepared" | "skipped" | "failed"
    resume_version_id: str | None = None
    lines: int = 0
    claim_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


def _cost_for_generation(gen: dict) -> float:
    """Deterministic $/1K-tokens cost per model. If the generation row already
    has `cost_usd` we trust it; otherwise fall back to a per-model default."""
    if gen.get("cost_usd") is not None:
        try:
            return float(gen["cost_usd"])
        except (TypeError, ValueError):
            pass
    provider = (gen.get("provider") or "").lower()
    model = (gen.get("model") or "").lower()
    # Emergent LLM key covers Claude Sonnet + Gemini + OpenAI. Approximate
    # $/M tokens (input); output ~3x input. These are used ONLY when the
    # generation didn't record cost — they're indicative, marked as such
    # in the response payload's `cost_source`.
    in_per_m = 3.0
    out_per_m = 15.0
    if "gpt-5" in model or "gpt5" in model:
        in_per_m, out_per_m = 5.0, 20.0
    elif "sonnet" in model or "claude" in model:
        in_per_m, out_per_m = 3.0, 15.0
    elif "gemini" in model or "flash" in model:
        in_per_m, out_per_m = 0.35, 1.4
    tin = int(gen.get("tokens_in") or 0)
    tout = int(gen.get("tokens_out") or 0)
    return (tin / 1_000_000.0) * in_per_m + (tout / 1_000_000.0) * out_per_m


async def _tally_costs(user_id: str, since: datetime, generation_ids: set[str]) -> dict:
    """Sum token + $ usage across the ai_generations rows created during the
    batch. Returns {tokens_in, tokens_out, cost_usd, has_recorded_costs}.
    """
    db = get_db()
    tokens_in = tokens_out = 0
    cost = 0.0
    has_recorded = True  # flip to False if any row lacks cost_usd
    q = {"user_id": user_id, "created_at": {"$gte": since}}
    if generation_ids:
        q["id"] = {"$in": list(generation_ids)}
    async for gen in db.ai_generations.find(q, {"_id": 0}):
        tokens_in += int(gen.get("tokens_in") or 0)
        tokens_out += int(gen.get("tokens_out") or 0)
        cost += _cost_for_generation(gen)
        if gen.get("cost_usd") is None:
            has_recorded = False
    return {"tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost_usd": round(cost, 6), "has_recorded_costs": has_recorded}


@router.post("/bulk-prepare")
async def bulk_prepare(req: BulkPrepareRequest,
                        user: dict = Depends(require_consent("generate_materials"))):
    started_at = datetime.now(timezone.utc)
    batch_id = str(uuid.uuid4())
    db = get_db()
    total_lines = 0
    total_claims = set()
    generation_ids: set[str] = set()
    items: list[BulkPrepareItemResult] = []

    # Ownership check for all application_ids up-front.
    owned = {r["id"] async for r in db.applications.find(
        {"id": {"$in": req.application_ids}, "user_id": user["id"]},
        {"id": 1, "_id": 0})}
    not_owned = [aid for aid in req.application_ids if aid not in owned]
    if not_owned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "error": "application_ids_not_owned",
            "invalid_ids": not_owned,
        })

    for aid in req.application_ids:
        t0 = time.time()
        try:
            row = await apps_svc.prepare_application(aid, user=user)
            lines = (((row or {}).get("materials") or {}).get("resume_version_id") and 1) or 0
            # Fetch the resume_version to count lines and claims accurately.
            rv = await db.resume_versions.find_one(
                {"application_id": aid, "user_id": user["id"]},
                sort=[("created_at", -1)], projection={"_id": 0},
            )
            manifest_lines = (rv or {}).get("render_manifest", {}).get("lines", [])
            claims_here: set[str] = set()
            for L in manifest_lines:
                for cid in (L.get("claim_ids") or []):
                    claims_here.add(cid)
                    total_claims.add(cid)
            for gid in ((rv or {}).get("render_manifest", {}).get("generations") or []):
                generation_ids.add(gid)
            total_lines += len(manifest_lines)
            items.append(BulkPrepareItemResult(
                application_id=aid, status="prepared",
                resume_version_id=(rv or {}).get("id"),
                lines=len(manifest_lines),
                claim_ids=sorted(claims_here),
            ))
        except HTTPException as e:
            reason = (e.detail if isinstance(e.detail, str)
                      else (e.detail or {}).get("error") or "http_error")
            items.append(BulkPrepareItemResult(
                application_id=aid, status="skipped", reason=reason,
            ))
        except Exception as e:  # pragma: no cover — surface unknowns truthfully
            items.append(BulkPrepareItemResult(
                application_id=aid, status="failed",
                reason=f"{type(e).__name__}: {str(e)[:200]}",
            ))
        finally:
            _ = time.time() - t0

    tally = await _tally_costs(user["id"], started_at, generation_ids)
    cost_per_1000_lines = None
    if total_lines > 0:
        cost_per_1000_lines = round(tally["cost_usd"] / (total_lines / 1000.0), 6)
    finished_at = datetime.now(timezone.utc)
    summary = {
        "batch_id": batch_id,
        "user_id": user["id"],
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_s": round((finished_at - started_at).total_seconds(), 3),
        "requested": len(req.application_ids),
        "prepared": sum(1 for i in items if i.status == "prepared"),
        "skipped": sum(1 for i in items if i.status == "skipped"),
        "failed": sum(1 for i in items if i.status == "failed"),
        "total_lines": total_lines,
        "distinct_claims_used": sorted(total_claims),
        "distinct_claim_count": len(total_claims),
        "cost": {
            "tokens_in": tally["tokens_in"],
            "tokens_out": tally["tokens_out"],
            "cost_usd": tally["cost_usd"],
            "cost_per_1000_lines_usd": cost_per_1000_lines,
            "cost_source": ("recorded" if tally["has_recorded_costs"]
                            else "indicative_from_per_model_defaults"),
        },
        "items": [i.model_dump() for i in items],
    }
    await db.bulk_prep_runs.insert_one({**summary, "created_at": utc_now()})
    await audit.write(user["id"], "prep.bulk", f"batch:{batch_id}",
                       {"requested": summary["requested"],
                        "prepared": summary["prepared"]})
    summary.pop("_id", None)
    return summary


@router.get("/bulk-prepare/runs")
async def list_runs(user: dict = Depends(require_consent("generate_materials"))):
    rows: list[dict] = []
    async for r in get_db().bulk_prep_runs.find({"user_id": user["id"]},
                                                  {"_id": 0, "items": 0}).sort("created_at", -1).limit(50):
        rows.append(r)
    return {"runs": rows, "total": len(rows)}


@router.get("/bulk-prepare/runs/{batch_id}")
async def get_run(batch_id: str,
                    user: dict = Depends(require_consent("generate_materials"))):
    row = await get_db().bulk_prep_runs.find_one({"user_id": user["id"], "batch_id": batch_id},
                                                    {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="bulk_prep_run_not_found")
    return row

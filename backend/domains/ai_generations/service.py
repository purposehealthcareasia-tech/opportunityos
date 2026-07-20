"""ai_generations — audit ledger for every tailoring/generation call.

Fields (spec-verbatim + a few operational extras):
  id, user_id, application_id (nullable), task, model, prompt_hash,
  claims_used: [uuid], validator_result: {status, passed_lines, rejected_lines, stats},
  tokens_in_est, tokens_out_est, cost_usd_est, outcome ("passed"|"failed"|"template_fallback"),
  attempt_index, ts
"""
from __future__ import annotations
import uuid
from typing import Any
from core.db import get_db
from core.time_utils import utc_now


async def insert(
    *,
    user_id: str,
    application_id: str | None,
    task: str,
    model: str,
    prompt_hash: str,
    claims_used: list[str],
    validator_result: dict[str, Any],
    tokens_in_est: int,
    tokens_out_est: int,
    cost_usd_est: float,
    outcome: str,
    attempt_index: int,
    error: str | None = None,
    instruction_hash: str | None = None,
    refusal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "application_id": application_id,
        "task": task,
        "model": model,
        "prompt_hash": prompt_hash,
        "instruction_hash": instruction_hash,
        "claims_used": list(claims_used or []),
        "validator_result": validator_result,
        "tokens_in_est": int(tokens_in_est),
        "tokens_out_est": int(tokens_out_est),
        "cost_usd_est": float(cost_usd_est or 0.0),
        "outcome": outcome,
        "attempt_index": attempt_index,
        "error": error,
        "refusal": refusal,
        "ts": utc_now(),
    }
    await get_db().ai_generations.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_for_application(application_id: str, user_id: str) -> list[dict]:
    cur = get_db().ai_generations.find(
        {"application_id": application_id, "user_id": user_id},
        {"_id": 0},
    ).sort("ts", -1)
    return [r async for r in cur]

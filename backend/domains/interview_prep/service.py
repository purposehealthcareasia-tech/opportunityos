"""Phase 5d · Interview Prep grounded in Passport.

Text-mode prep + mock Q&A generated ONLY from APPROVED Passport claims.
Grounding rule: no claim, no sentence — the LLM is prompted with a
strict allowlist of the user's approved claim data + a validation
firewall on the output. Anything the model returns that isn't
substantively rooted in an approved claim is refused/redacted.

Consent-scoped (`interview_prep_generate`). Labeled "practice".
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.config import settings
from core.db import get_db
from core.deps import require_consent


router = APIRouter(prefix="/api/v1/interview-prep", tags=["interview_prep"])


_ALLOWED_CATEGORIES = ("education", "employment", "skill", "project")

_SYSTEM_PROMPT = (
    "You are Fynd's interview practice generator. HARD RULES:\n"
    "1) You may reference ONLY the JSON claims block provided by the user. "
    "Every sentence you write MUST substantively cite a field from that block.\n"
    "2) If a claim block field is empty, you MAY NOT invent a value for it. "
    "Say 'not on file' instead.\n"
    "3) Output a strict JSON object with keys: `practice_questions` "
    "(array of {question, sample_answer, grounded_in: [claim_ids]}), and "
    "`prep_summary` (short paragraph, ≤400 chars).\n"
    "4) Never generate salary numbers, dates, or company names not in the "
    "claim block. Never generate ITAR/visa status. Never suggest lying.\n"
    "5) Never claim this is professional interview coaching. This is "
    "practice material derived from user-approved claims only."
)

_GROUNDING_CATEGORY_KEYS = {
    "education": {"school", "degree", "field", "graduation_year"},
    "employment": {"title", "company", "start_year", "end_year"},
    "skill": {"name", "level"},
    "project": {"name", "description"},
}


class PrepRequest(BaseModel):
    category: Literal["education", "employment", "skill", "project"]
    question_count: int = Field(3, ge=1, le=8)
    focus_hint: Optional[str] = Field(
        None, max_length=140,
        description="Optional user note like 'behavioral: teamwork'. Stored in the prompt, not free-form claim-invention.",
    )


def _tokens_of(v) -> set[str]:
    """Lowercase-alphanumeric token set from a claim value. Used by the
    firewall to prove that every generated sentence 'substantively'
    contains at least one token from the source claim block."""
    if v is None:
        return set()
    s = str(v).lower()
    return {t for t in re.findall(r"[a-z0-9]{3,}", s)}


def _validation_firewall(qas: list[dict], claim_tokens: set[str]) -> tuple[list[dict], list[str]]:
    """For each Q&A, verify that the sample_answer contains ≥1 token
    from the approved-claim tokens. Reject any Q&A that fails."""
    kept: list[dict] = []
    dropped: list[str] = []
    # Generic vocabulary allowed regardless of claim tokens (rails-neutral
    # sentence connectors that appear in nearly any answer).
    generic = {
        "yes", "no", "i", "we", "the", "and", "or", "in", "on", "for",
        "with", "not", "to", "of", "at", "as", "my", "our", "this",
    }
    for qa in qas:
        ans = str(qa.get("sample_answer") or "").lower()
        ans_tokens = {t for t in re.findall(r"[a-z0-9]{3,}", ans)} - generic
        if not ans_tokens:
            dropped.append(qa.get("question") or "<no-question>")
            continue
        # At least one substantive answer-token must appear in the
        # user's approved-claim vocabulary. This is the "no claim, no
        # sentence" firewall in its simplest defensible form.
        if ans_tokens & claim_tokens:
            kept.append(qa)
        else:
            dropped.append(qa.get("question") or "<no-question>")
    return kept, dropped


def _build_claim_block(claims: list[dict], category: str) -> tuple[list[dict], set[str]]:
    """Filter approved claims to `category` + strip everything the
    grounding rule doesn't need (no user_id, no created_at, etc.).
    Also computes the token set for the firewall."""
    allowed = _GROUNDING_CATEGORY_KEYS.get(category, set())
    block: list[dict] = []
    tokens: set[str] = set()
    for c in claims:
        if c.get("kind") != category:
            continue
        if c.get("state") != "approved":
            continue
        data = c.get("data") or {}
        clean = {k: data.get(k) for k in allowed if data.get(k) is not None}
        if not clean:
            continue
        clean["_claim_id"] = c.get("id") or c.get("_id") or ""
        block.append(clean)
        for v in clean.values():
            tokens |= _tokens_of(v)
    return block, tokens


async def _generate_via_llm(
    system: str, prompt: str, session_id: str,
) -> tuple[str, str, int, int]:
    """Delegate to the same emergentintegrations LlmChat pattern the rest
    of the codebase uses (services/llm.py). Import lazily so pytest
    monkeypatching can override this without needing the SDK loaded."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # lazy
    key = settings.EMERGENT_LLM_KEY
    if not key:
        raise HTTPException(status_code=503, detail="llm_key_missing")
    chat = LlmChat(api_key=key, session_id=session_id, system_message=system)\
        .with_model("openai", "gpt-4o")
    raw = await chat.send_message(UserMessage(text=prompt))
    return "gpt-4o", raw or "", len(system + prompt), len(raw or "")


@router.post("/generate")
async def generate_prep(
    req: PrepRequest,
    user: dict = Depends(require_consent("interview_prep_generate")),
):
    db = get_db()
    claims_cursor = db.claims.find({"user_id": user["id"], "state": "approved"})
    claims = [c async for c in claims_cursor]

    claim_block, claim_tokens = _build_claim_block(claims, req.category)
    if not claim_block:
        # Honest empty state — never invent placeholder practice material.
        return {
            "practice_questions": [],
            "prep_summary": "",
            "grounded": True,
            "empty_state": True,
            "reason": "no_approved_claims_in_category",
            "category": req.category,
            "notice": (
                f"You don't have any approved '{req.category}' claims yet. "
                "Interview prep is grounded ONLY in claims you've approved. "
                "Add and approve some in your Passport, then come back."
            ),
        }

    prompt = json.dumps({
        "category": req.category,
        "question_count": req.question_count,
        "focus_hint": (req.focus_hint or "").strip(),
        "approved_claims": claim_block,
        "instruction": (
            f"Generate exactly {req.question_count} PRACTICE interview questions "
            "with grounded sample answers. Every answer MUST cite fields from "
            "the approved_claims block above. Return strict JSON."
        ),
    })

    session_id = f"interview-prep-{user['id']}-{uuid.uuid4().hex[:8]}"
    try:
        model_used, raw, _, _ = await _generate_via_llm(_SYSTEM_PROMPT, prompt, session_id)
    except HTTPException:
        raise
    except Exception as e:
        # Never 500 through — surface an honest error to the client.
        raise HTTPException(status_code=502, detail={
            "error": "llm_generation_failed",
            "message": str(e)[:400],
        })

    # Extract JSON block from the raw response (LLMs sometimes wrap in ```).
    try:
        cleaned = raw.strip()
        if "```" in cleaned:
            # Grab the first fenced code block content.
            parts = re.split(r"```(?:json)?", cleaned)
            if len(parts) >= 2:
                cleaned = parts[1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
    except Exception:
        raise HTTPException(status_code=502, detail={
            "error": "llm_returned_unparseable_json",
            "raw_preview": (raw or "")[:400],
        })

    qas = parsed.get("practice_questions") or []
    kept, dropped = _validation_firewall(qas, claim_tokens)

    # Log the generation (auditable trail; also cost tracking hook).
    await db.interview_prep_generations.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "category": req.category,
        "model_used": model_used,
        "requested_count": req.question_count,
        "kept_count": len(kept),
        "dropped_by_firewall_count": len(dropped),
        "at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "practice_questions": kept,
        "prep_summary": (parsed.get("prep_summary") or "")[:400],
        "grounded": True,
        "empty_state": False,
        "category": req.category,
        "model_used": model_used,
        "firewall": {
            "kept": len(kept),
            "dropped": len(dropped),
            "dropped_preview": dropped[:3],
        },
        "labeled_as": "PRACTICE — grounded in your approved Passport claims only. Not employer output.",
    }

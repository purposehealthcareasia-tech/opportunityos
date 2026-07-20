"""Grounded LLM parse for résumé text → draft claims.

Model policy (Phase 2 pin):
- Primary:  openai / gpt-5
- Fallback: openai / gpt-4o

The SYSTEM prompt is deliberately anti-fabrication. If the model can't ground a fact in the text,
it MUST omit that claim rather than hallucinate.

Founder Directive #8 (Phase 3): per-task model-cost logging. Every call appends to `llm_costs`:
  { user_id, task, model, tokens_in, tokens_out, cost_usd_est, ts, session_id }
"""
import json
import logging
import re
import uuid
from typing import Any
from emergentintegrations.llm.chat import LlmChat, UserMessage
from core.config import settings
from core.db import get_db
from core.time_utils import utc_now

log = logging.getLogger("oppos.llm")

PRIMARY_MODEL = "gpt-5"
FALLBACK_MODEL = "gpt-4o"
PROVIDER = "openai"

# Public price cards (USD per 1K tokens) — used ONLY as estimates for cost ledger.
# We record the estimate honestly; when the provider surfaces the true billed amount
# the ledger can be reconciled offline. If a model isn't in the table we store 0 and a
# note. NEVER guess; only estimate against published rack rate.
_PRICE_TABLE_PER_1K = {
    # OpenAI (approx, published Feb 2026)
    "gpt-5":    {"in": 0.00500, "out": 0.01500, "source": "openai:public_2026-02"},
    "gpt-4o":   {"in": 0.00250, "out": 0.01000, "source": "openai:public_2026-02"},
}


def _rough_tokens(text: str) -> int:
    """Rough tokenizer proxy: ~4 chars/token English. Good enough for cost estimation."""
    if not text:
        return 0
    return max(1, int(len(text) / 4))


async def _write_cost_row(
    *, user_id: str | None, task: str, model: str, tokens_in: int, tokens_out: int,
    session_id: str, extra: dict[str, Any] | None = None,
) -> None:
    card = _PRICE_TABLE_PER_1K.get(model, {"in": 0.0, "out": 0.0, "source": "unknown_model"})
    cost = (tokens_in / 1000.0) * card["in"] + (tokens_out / 1000.0) * card["out"]
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "task": task,
        "model": model,
        "provider": PROVIDER,
        "tokens_in_est": int(tokens_in),
        "tokens_out_est": int(tokens_out),
        "cost_usd_est": round(cost, 6),
        "price_source": card.get("source"),
        "session_id": session_id,
        "ts": utc_now(),
        "extra": extra or {},
    }
    try:
        await get_db().llm_costs.insert_one(row)
    except Exception:
        log.exception("Failed to persist llm_costs row")


ALLOWED_TYPES = {
    "identity", "contact", "location", "work_auth", "visa_timeline",
    "education", "employment", "project", "skill", "certification",
    "publication", "reference", "comp_expectation", "availability",
    "preference", "screener_answer", "link",
}

SYSTEM_PROMPT = """You are OpportunityOS's résumé extractor.

Your job is to convert a résumé's plain text into an array of atomic "claims".

HARD RULES (violation = failure):
1. Every claim MUST be grounded in the résumé text. If a fact is not textually present, DO NOT include it.
2. NEVER invent employers, dates, degrees, cities, skills, or metrics. If ambiguous, omit.
3. NEVER guess work-authorization or immigration status. If not written explicitly, omit that claim.
4. Return VALID JSON matching the schema below and nothing else — no prose, no markdown fences.
5. If the résumé is empty or unusable, return {"claims": []}.

SCHEMA:
{
  "claims": [
    {
      "type": one of: identity, contact, location, education, employment, project, skill, certification, publication, link,
      "value": object with type-specific fields (see below),
      "confidence": float in [0.0, 1.0]  // your confidence that the CLAIM is textually supported
    }
  ]
}

TYPE-SPECIFIC VALUE FIELDS (include only fields you actually saw):
- identity      : { name }
- contact       : { email?, phone? }
- location      : { city?, state?, country? }
- education     : { institution?, degree?, field?, start?, end?, expected_graduation?, gpa? }
- employment    : { company, role, start?, end?, summary?, tools?[] }
- project       : { title, summary?, tools?[], metric?{name,value,type} }
- skill         : { name }  // ONE skill per claim (split lists into individual claims)
- certification : { name, issuer?, year? }
- publication   : { title, venue?, year? }
- link          : { kind, url }  // kind = website|github|linkedin|scholar|other

Emit at most 60 claims. Split skill lists so each skill is its own claim. Do NOT emit work_auth,
visa_timeline, comp_expectation, availability, preference, or screener_answer — those belong to
other onboarding flows.
"""


def _extract_json(raw: str) -> dict[str, Any]:
    """Tolerant JSON extractor: strips markdown fences and grabs the first {…} block."""
    if not raw:
        raise ValueError("empty_response")
    s = raw.strip()
    # Strip markdown fences if the model added them despite instructions
    s = re.sub(r"^```(?:json)?", "", s.strip(), flags=re.IGNORECASE).strip()
    s = re.sub(r"```$", "", s.strip()).strip()
    if not s.startswith("{"):
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            raise ValueError("no_json_object_found")
        s = m.group(0)
    return json.loads(s)


def _normalize_claims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    claims_in = payload.get("claims", []) or []
    out: list[dict[str, Any]] = []
    for c in claims_in:
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type", "")).strip().lower()
        if ctype not in ALLOWED_TYPES:
            continue
        value = c.get("value")
        if not isinstance(value, dict) or not any(v not in (None, "", []) for v in value.values()):
            continue
        confidence = c.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None
        out.append({"type": ctype, "value": value, "confidence": confidence})
    return out


async def _call_model(model: str, text: str, session_id: str) -> tuple[str, str]:
    key = settings.EMERGENT_LLM_KEY
    if not key:
        raise RuntimeError("EMERGENT_LLM_KEY not set")
    chat = LlmChat(
        api_key=key,
        session_id=session_id,
        system_message=SYSTEM_PROMPT,
    ).with_model(PROVIDER, model)
    prompt_body = f"RESUME TEXT (verbatim):\n---\n{text}\n---"
    raw = await chat.send_message(UserMessage(text=prompt_body))
    return model, raw, _rough_tokens(SYSTEM_PROMPT + prompt_body), _rough_tokens(raw or "")


async def parse_resume_text(text: str, document_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Return {model_used, raw_len, claims}. Tries PRIMARY then FALLBACK on JSON failure.

    Founder Directive #8: appends per-attempt cost rows to `llm_costs` (even for the failed
    primary attempt when we fall back — cost is real).
    """
    text = (text or "").strip()
    if not text:
        return {"model_used": None, "claims": [], "raw_len": 0, "note": "empty_text"}

    session = f"resume-parse-{document_id}-{uuid.uuid4().hex[:6]}"
    last_error: Exception | None = None
    for candidate in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            model_used, raw, tokens_in, tokens_out = await _call_model(candidate, text, session)
            await _write_cost_row(
                user_id=user_id,
                task="resume_parse",
                model=model_used,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                session_id=session,
                extra={"document_id": document_id, "outcome": "success"},
            )
            payload = _extract_json(raw)
            claims = _normalize_claims(payload)
            log.info("parse_resume_text OK model=%s claims=%d raw_len=%d", model_used, len(claims), len(raw))
            return {"model_used": model_used, "claims": claims, "raw_len": len(raw)}
        except Exception as e:
            last_error = e
            # Best-effort cost row for the failed attempt so the ledger is complete.
            await _write_cost_row(
                user_id=user_id,
                task="resume_parse",
                model=candidate,
                tokens_in=_rough_tokens(SYSTEM_PROMPT + text),
                tokens_out=0,
                session_id=session,
                extra={"document_id": document_id, "outcome": "failed", "error": str(e)[:200]},
            )
            log.warning("parse attempt failed model=%s err=%s", candidate, e)
            continue
    raise RuntimeError(f"parse_failed: {last_error}")

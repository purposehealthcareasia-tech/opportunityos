"""Grounded LLM parse for résumé text → draft claims.

Model policy (Phase 2 pin):
- Primary:  openai / gpt-5
- Fallback: openai / gpt-4o

The SYSTEM prompt is deliberately anti-fabrication. If the model can't ground a fact in the text,
it MUST omit that claim rather than hallucinate.
"""
import json
import logging
import re
import uuid
from typing import Any
from emergentintegrations.llm.chat import LlmChat, UserMessage
from core.config import settings

log = logging.getLogger("oppos.llm")

PRIMARY_MODEL = "gpt-5"
FALLBACK_MODEL = "gpt-4o"
PROVIDER = "openai"

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
    raw = await chat.send_message(UserMessage(text=f"RESUME TEXT (verbatim):\n---\n{text}\n---"))
    return model, raw


async def parse_resume_text(text: str, document_id: str) -> dict[str, Any]:
    """Return {model_used, raw_len, claims}. Tries PRIMARY then FALLBACK on JSON failure."""
    text = (text or "").strip()
    if not text:
        return {"model_used": None, "claims": [], "raw_len": 0, "note": "empty_text"}

    session = f"resume-parse-{document_id}-{uuid.uuid4().hex[:6]}"
    last_error: Exception | None = None
    for candidate in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            model_used, raw = await _call_model(candidate, text, session)
            payload = _extract_json(raw)
            claims = _normalize_claims(payload)
            log.info("parse_resume_text OK model=%s claims=%d raw_len=%d", model_used, len(claims), len(raw))
            return {"model_used": model_used, "claims": claims, "raw_len": len(raw)}
        except Exception as e:
            last_error = e
            log.warning("parse attempt failed model=%s err=%s", candidate, e)
            continue
    raise RuntimeError(f"parse_failed: {last_error}")

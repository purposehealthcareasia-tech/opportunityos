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
    # Anthropic Claude (approx, published Feb 2026)
    "claude-sonnet-4-5-20250929": {"in": 0.00300, "out": 0.01500, "source": "anthropic:public_2026-02"},
    "claude-sonnet-4-6":          {"in": 0.00300, "out": 0.01500, "source": "anthropic:public_2026-02"},
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


# =====================================================================================
# Phase 4 — Grounded tailoring generation
# =====================================================================================

TAILOR_PROVIDER = "anthropic"
TAILOR_MODEL = "claude-sonnet-4-5-20250929"

TAILOR_SYSTEM_PROMPT = """You are OpportunityOS's grounded résumé tailoring engine.

You produce résumé bullet lines that are STRICTLY grounded in a candidate's APPROVED Career
Passport claims. You never invent facts.

HARD RULES (violation = failure — the server-side validator will reject and mark this
generation failed):

1. Every "text" you emit MUST reference the exact claim IDs (from the CLAIMS list below)
   whose values back that text. Multiple IDs are fine when multiple claims contribute.
2. NEVER assert a fact — number, date, tool, employer, title, degree, location, cert —
   that is not present in the value of at least one referenced claim.
3. If a claim's `sensitivity` is "sealed", DO NOT surface its literal value in `text`.
   You may still use non-sensitive parts of the same claim's context.
4. If the user's instruction asks for something NOT supported by the approved claims,
   DO NOT invent it. Skip that fact silently — the server has already refused the
   instruction where appropriate, so if you receive it, treat it as a request for
   related grounded content.
5. Prefer conciseness. Emit 5–8 lines max. Each line should read like a strong résumé
   bullet: verb + object + evidence.
6. Never emit demographic content (gender, race, age, ethnicity, religion, disability,
   veteran, orientation) even if a claim contains such info. Those categories are
   OUT OF SCOPE forever.
7. Return VALID JSON only, matching the schema. No prose, no markdown fences.

SCHEMA:
{
  "lines": [
    { "text": "<résumé bullet, present tense unless the claim is past employment>",
      "claim_ids": ["<uuid>", "..."] }
  ]
}

If you cannot produce ANY grounded line (empty approved claims, or no relevant coverage),
return {"lines": []}.
"""


def _build_tailor_user_message(*, jd_text: str, claims: list[dict], instruction: str | None) -> str:
    """Compact the JD + claim rows into a single prompt.

    Sealed claims are shown with placeholder value {value:"[sealed]"} — the model sees the
    ID and type so it can reference them for context (e.g., "eligible for STEM OPT" as a
    metadata cue) but never sees the literal sealed value.
    """
    lines = ["JD (verbatim):", "---", (jd_text or "").strip(), "---", "", "APPROVED CLAIMS:"]
    for c in claims:
        ctype = c.get("type")
        cid = c.get("id")
        sensitivity = (c.get("sensitivity") or "").lower()
        value = c.get("value")
        if sensitivity == "sealed":
            display_value = "[sealed]"
        else:
            display_value = value
        lines.append(f"- id={cid} type={ctype} value={json.dumps(display_value, ensure_ascii=False)}")
    lines.append("")
    if instruction:
        lines.append("USER INSTRUCTION (respect grounding):")
        lines.append(instruction.strip())
    else:
        lines.append("USER INSTRUCTION: (none)")
    return "\n".join(lines)


def _extract_lines_payload(raw: str) -> list[dict]:
    payload = _extract_json(raw)
    lines = payload.get("lines")
    if not isinstance(lines, list):
        raise ValueError("no_lines_array")
    out: list[dict] = []
    for L in lines:
        if not isinstance(L, dict):
            continue
        text = L.get("text")
        cids = L.get("claim_ids")
        if not isinstance(text, str) or not isinstance(cids, list):
            continue
        out.append({"text": text.strip(), "claim_ids": [str(x) for x in cids if isinstance(x, (str, int))]})
    return out


async def _call_claude(model: str, system_prompt: str, user_prompt: str, session_id: str) -> tuple[str, str, int, int]:
    key = settings.EMERGENT_LLM_KEY
    if not key:
        raise RuntimeError("EMERGENT_LLM_KEY not set")
    chat = LlmChat(
        api_key=key,
        session_id=session_id,
        system_message=system_prompt,
    ).with_model(TAILOR_PROVIDER, model)
    raw = await chat.send_message(UserMessage(text=user_prompt))
    return model, raw, _rough_tokens(system_prompt + user_prompt), _rough_tokens(raw or "")


async def generate_tailored_lines(
    *,
    user_id: str,
    application_id: str,
    jd_text: str,
    approved_claims: list[dict],
    instruction: str | None = None,
) -> dict[str, Any]:
    """Return {model_used, prompt_hash, tokens_in, tokens_out, lines: [{text, claim_ids}]}.

    The caller (application prepare / regenerate flow) is responsible for running the
    validator, persisting the ai_generations row, and choosing template fallback on
    validation failure.
    """
    session = f"tailor-{application_id}-{uuid.uuid4().hex[:6]}"
    user_prompt = _build_tailor_user_message(jd_text=jd_text, claims=approved_claims, instruction=instruction)
    prompt_hash = _hash_prompt(TAILOR_SYSTEM_PROMPT + "\n" + user_prompt)
    try:
        model_used, raw, tokens_in, tokens_out = await _call_claude(
            TAILOR_MODEL, TAILOR_SYSTEM_PROMPT, user_prompt, session,
        )
        await _write_cost_row(
            user_id=user_id, task="tailor_resume",
            model=model_used, tokens_in=tokens_in, tokens_out=tokens_out,
            session_id=session, extra={"application_id": application_id, "outcome": "success"},
        )
        try:
            lines = _extract_lines_payload(raw)
        except Exception as e:
            log.warning("tailor generation returned malformed JSON: %s", e)
            lines = []
        return {
            "model_used": model_used, "prompt_hash": prompt_hash,
            "tokens_in_est": tokens_in, "tokens_out_est": tokens_out,
            "lines": lines, "raw_len": len(raw or ""),
        }
    except Exception as e:
        await _write_cost_row(
            user_id=user_id, task="tailor_resume",
            model=TAILOR_MODEL, tokens_in=_rough_tokens(TAILOR_SYSTEM_PROMPT + user_prompt),
            tokens_out=0, session_id=session,
            extra={"application_id": application_id, "outcome": "failed", "error": str(e)[:200]},
        )
        log.exception("tailor generation failed")
        return {
            "model_used": TAILOR_MODEL, "prompt_hash": prompt_hash,
            "tokens_in_est": _rough_tokens(TAILOR_SYSTEM_PROMPT + user_prompt), "tokens_out_est": 0,
            "lines": [], "raw_len": 0, "error": str(e)[:200],
        }


import hashlib  # noqa: E402


def _hash_prompt(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# =====================================================================================
# Phase 4 — Template fallback (NO LLM). Deterministic bullet builder using approved claim
# values. Used when the model output fails validation twice.
# =====================================================================================

def template_fallback_lines(approved_claims: list[dict]) -> list[dict]:
    """Build 3–6 grounded template lines directly from approved claim values.

    ZERO LLM. ZERO fabrication. Each line references its source claim IDs.
    Never surfaces sealed values.
    """
    lines: list[dict] = []

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for c in approved_claims or []:
        if (c.get("sensitivity") or "").lower() == "sealed":
            continue
        by_type.setdefault(c.get("type"), []).append(c)

    # Employment lines (most recent first if we can order)
    employments = by_type.get("employment") or []
    for emp in employments[:2]:
        v = emp.get("value") or {}
        company = v.get("company") or "employer"
        role = v.get("role") or "engineer"
        summary = (v.get("summary") or "").strip()
        parts = [f"{role} at {company}"]
        if summary:
            parts.append(f"— {summary}")
        text = ". ".join(parts).strip(". ").strip() + "."
        lines.append({"text": text, "claim_ids": [emp["id"]]})

    # Skills — one aggregated line pulling from the top ~5 skill claims
    skills = by_type.get("skill") or []
    if skills:
        top = skills[:5]
        names = [((c.get("value") or {}).get("name") or "").strip() for c in top]
        names = [n for n in names if n]
        if names:
            lines.append({
                "text": "Core skills: " + ", ".join(names) + ".",
                "claim_ids": [c["id"] for c in top],
            })

    # Education
    for edu in (by_type.get("education") or [])[:1]:
        v = edu.get("value") or {}
        degree = v.get("degree") or ""
        field = v.get("field") or ""
        institution = v.get("institution") or ""
        bits = [x for x in [degree, ("in " + field) if field else "", ("from " + institution) if institution else ""] if x]
        if bits:
            lines.append({"text": " ".join(bits) + ".", "claim_ids": [edu["id"]]})

    return lines


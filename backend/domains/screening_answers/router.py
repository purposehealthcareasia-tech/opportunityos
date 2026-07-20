"""Screening answers — grounded, library-reusable, sensitive-safe.

Categories (kind):
  - "normal"           : grounded generation OK, library reuse OK, user typing OK.
  - "sensitive_visa"   : NEVER auto-generated. User types OR picks from library. Per-application approval required.
  - "sensitive_salary" : same.
  - "sensitive_clearance": same.
  - "demographic"      : rendered as static informational text on the UI. NO storage code path.
                         Any POST that carries kind=demographic returns 400.

Provenance (per spec):
  - "library"    : reused from user's saved library.
  - "generated"  : produced by grounded LLM (only for normal kind).
  - "user"       : typed directly.
"""
from __future__ import annotations
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from core.db import get_db
from core.deps import get_current_user, require_consent
from core.time_utils import utc_now
from domains.audit import service as audit
from services import validator as validator_svc
from services import llm as llm_svc
from domains.ai_generations import service as ai_gen_svc


router = APIRouter(prefix="/api/v1", tags=["screeners"])


SENSITIVE_KINDS = {"sensitive_visa", "sensitive_salary", "sensitive_clearance"}
FORBIDDEN_KINDS = {"demographic"}  # Never stored. Ever.


class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=4000)
    provenance: str = Field(default="user")  # 'user' | 'library'
    approved: bool = Field(default=False)


class GenerateAnswerRequest(BaseModel):
    instruction: str | None = None


class SaveToLibraryRequest(BaseModel):
    category: str
    question_pattern: str
    answer: str
    sensitive: bool = False


@router.get("/applications/{application_id}/screeners")
async def list_screeners(application_id: str, user: dict = Depends(get_current_user)):
    """Return the application's screener questions merged with any answers."""
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    job = await db.jobs.find_one({"id": app_row["job_id"]}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    questions: list[dict] = list(job.get("screener_questions") or [])
    # Load existing answers for THIS application
    ans_cur = db.screening_answers.find(
        {"user_id": user["id"], "application_id": application_id},
        {"_id": 0},
    )
    ans_by_qid = {a["question_id"]: a async for a in ans_cur}
    result: list[dict] = []
    for q in questions:
        qid = q["id"]
        result.append({
            "question_id": qid,
            "category": q.get("category"),
            "question_pattern": q.get("question_pattern"),
            "kind": q.get("kind"),   # normal / sensitive_visa / sensitive_salary / sensitive_clearance / demographic
            "text": q.get("text"),
            "sensitive": q.get("kind") in SENSITIVE_KINDS,
            "static_only": q.get("kind") in FORBIDDEN_KINDS,  # UI: render as static text
            "answer": ans_by_qid.get(qid, {}).get("answer"),
            "provenance": ans_by_qid.get(qid, {}).get("provenance"),
            "approved": ans_by_qid.get(qid, {}).get("approved", False),
            "updated_at": ans_by_qid.get(qid, {}).get("updated_at"),
        })
    return {"application_id": application_id, "questions": result}


def _find_q(job: dict, question_id: str) -> dict | None:
    for q in (job.get("screener_questions") or []):
        if q.get("id") == question_id:
            return q
    return None


@router.post("/applications/{application_id}/screeners/{question_id}/answer")
async def answer_screener(
    application_id: str, question_id: str,
    req: AnswerRequest,
    user: dict = Depends(get_current_user),
):
    """Store a user- or library-typed answer for a screener question.

    HARD RULE: kind='demographic' MUST 400. Even if the client fakes the payload we
    refuse to persist any demographic response. Sensitive kinds default to approved=False;
    the user must explicitly re-POST with approved=true after review.
    """
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    job = await db.jobs.find_one({"id": app_row["job_id"]}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    q = _find_q(job, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="question_not_found")
    if q.get("kind") in FORBIDDEN_KINDS:
        raise HTTPException(
            status_code=400,
            detail={"error": "demographic_answers_never_stored",
                    "message": "OpportunityOS never stores demographic answers. Answer these directly on the employer's form."},
        )
    if req.provenance not in ("user", "library"):
        raise HTTPException(status_code=400, detail={"error": "invalid_provenance",
                                                       "allowed": ["user", "library"]})
    kind = q.get("kind")
    sensitive = kind in SENSITIVE_KINDS
    now = utc_now()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": application_id,
        "question_id": question_id,
        "category": q.get("category"),
        "question_pattern": q.get("question_pattern"),
        "kind": kind,
        "answer": req.answer.strip(),
        "provenance": req.provenance,
        "approved": bool(req.approved) if not sensitive else bool(req.approved),
        "sensitive": sensitive,
        "created_at": now,
        "updated_at": now,
        "order_hint": q.get("order_hint", 0),
    }
    await db.screening_answers.update_one(
        {"user_id": user["id"], "application_id": application_id, "question_id": question_id},
        {"$set": row},
        upsert=True,
    )
    await audit.write(user["id"], "screener.answer", f"application:{application_id}",
                      {"question_id": question_id, "provenance": row["provenance"],
                       "sensitive": sensitive, "approved": row["approved"]})
    return row


@router.post("/applications/{application_id}/screeners/{question_id}/generate")
async def generate_screener_answer(
    application_id: str, question_id: str,
    req: GenerateAnswerRequest,
    user: dict = Depends(require_consent("generate_materials")),
):
    """Grounded answer generation for NORMAL questions ONLY. Sensitive/demographic → 400."""
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    job = await db.jobs.find_one({"id": app_row["job_id"]}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    q = _find_q(job, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="question_not_found")
    kind = q.get("kind")
    if kind in FORBIDDEN_KINDS:
        raise HTTPException(status_code=400, detail={"error": "demographic_never_generated"})
    if kind in SENSITIVE_KINDS:
        raise HTTPException(
            status_code=400,
            detail={"error": "sensitive_never_generated",
                    "kind": kind,
                    "message": "Visa / salary / clearance answers are never AI-generated. Type them or pick from your library."},
        )
    # Grounded generation using the same tailoring pipeline, but with the question as JD text.
    approved_claims = []
    cur = db.claims.find({"user_id": user["id"], "status": "approved", "superseded_by": None}, {"_id": 0})
    async for c in cur:
        approved_claims.append(c)
    jd = f"Question: {q.get('text')}\n\nAnswer in 2–3 sentences, grounded strictly in the candidate's approved claims."
    gen = await llm_svc.generate_tailored_lines(
        user_id=user["id"], application_id=application_id,
        jd_text=jd, approved_claims=approved_claims,
        instruction=req.instruction or None,
    )
    vres = validator_svc.validate_lines(lines=gen["lines"], approved_claims=approved_claims)
    text = ""
    if vres.status == "passed" and vres.passed_lines:
        text = " ".join(L["text"] for L in vres.passed_lines)
    cost = (gen["tokens_in_est"] / 1000.0) * llm_svc._PRICE_TABLE_PER_1K.get(gen["model_used"], {"in": 0.0, "out": 0.0})["in"] \
         + (gen["tokens_out_est"] / 1000.0) * llm_svc._PRICE_TABLE_PER_1K.get(gen["model_used"], {"in": 0.0, "out": 0.0})["out"]
    claims_used = sorted({cid for L in gen["lines"] for cid in (L.get("claim_ids") or [])})
    await ai_gen_svc.insert(
        user_id=user["id"], application_id=application_id, task="tailor_screener",
        model=gen["model_used"], prompt_hash=gen["prompt_hash"],
        claims_used=claims_used, validator_result=vres.to_dict(),
        tokens_in_est=gen["tokens_in_est"], tokens_out_est=gen["tokens_out_est"],
        cost_usd_est=cost, outcome=vres.status, attempt_index=1,
    )
    return {
        "question_id": question_id,
        "generated_answer": text,
        "provenance": "generated",
        "validator_result": vres.to_dict(),
    }


@router.get("/screening-answers/library")
async def list_library(user: dict = Depends(get_current_user)):
    cur = get_db().screening_answers.find(
        {"user_id": user["id"], "application_id": None},
        {"_id": 0},
    ).sort("updated_at", -1)
    return {"library": [a async for a in cur]}


@router.post("/screening-answers/library")
async def save_to_library(req: SaveToLibraryRequest, user: dict = Depends(get_current_user)):
    if req.category in FORBIDDEN_KINDS:
        raise HTTPException(status_code=400, detail={"error": "demographic_never_stored"})
    now = utc_now()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": None,
        "question_id": None,
        "category": req.category,
        "question_pattern": req.question_pattern,
        "kind": req.category,
        "answer": req.answer.strip(),
        "provenance": "user",
        "approved": False,   # library rows have no application scope
        "sensitive": bool(req.sensitive),
        "created_at": now,
        "updated_at": now,
    }
    await get_db().screening_answers.insert_one(row)
    await audit.write(user["id"], "screening_library.save", "screening_answers:library",
                      {"category": req.category})
    row.pop("_id", None)
    return row

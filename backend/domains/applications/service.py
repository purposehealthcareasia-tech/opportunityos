import uuid
from fastapi import APIRouter, Depends
from pymongo.errors import DuplicateKeyError
from core.db import get_db
from core.deps import get_current_user, require_consent
from core.time_utils import utc_now
from domains.audit import service as audit

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])


class DuplicateApplication(Exception):
    pass


def route_decision(job: dict) -> dict:
    """Router v0.1 — returns only guided_manual | email_application | manual_queue.

    api_native and extension_assisted remain enum values for future phases but are NEVER emitted by
    this router in v0.1.
    """
    method = str(job.get("apply_method") or "").lower()
    if method.startswith("ats-") or method == "external":
        return {
            "route": "guided_manual",
            "rationale": "Employer uses an ATS-hosted application. Guided manual keeps the applicant transparent to the employer.",
        }
    if method == "email":
        return {
            "route": "email_application",
            "rationale": "Employer accepts email applications. We’ll help draft — you send.",
        }
    # internal / unknown / api
    return {
        "route": "manual_queue",
        "rationale": "Routing is pending a human review. Materials get prepared; a person confirms the path before send.",
    }


async def shortlist(user_id: str, job: dict) -> dict:
    r = route_decision(job)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "job_id": job["id"],
        "company_id": job.get("company_id"),
        "job_snapshot": {
            "title": job.get("title"),
            "company_name": job.get("company_name"),
            "canonical_key": job.get("canonical_key"),
            "is_sample": bool(job.get("is_sample")),
        },
        "state": "shortlisted",
        "route": r["route"],
        "route_rationale": r["rationale"],
        "materials": {},
        "authorization_id": None,
        "minutes_to_prepare": None,
        "fields_corrected": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    try:
        await get_db().applications.insert_one(doc)
    except DuplicateKeyError:
        raise DuplicateApplication()
    await audit.write(user_id, "application.shortlist", f"application:{doc['id']}", {"job_id": job["id"], "route": r["route"]})
    return {
        "id": doc["id"],
        "job_id": doc["job_id"],
        "state": doc["state"],
        "route": doc["route"],
        "route_rationale": doc["route_rationale"],
        "created_at": doc["created_at"],
        "job_snapshot": doc["job_snapshot"],
    }


@router.get("")
async def list_my_apps(user: dict = Depends(get_current_user)):
    cur = get_db().applications.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    apps = [a async for a in cur]
    return {"applications": apps}


from pydantic import BaseModel  # noqa: E402
from domains.applications.repository import atomic_transition, InvalidTransition, ALLOWED_TRANSITIONS  # noqa: E402
from fastapi import HTTPException, status  # noqa: E402


class StateTransitionRequest(BaseModel):
    expected_state: str
    new_state: str


@router.patch("/{application_id}/state")
async def transition_state(
    application_id: str,
    req: StateTransitionRequest,
    user: dict = Depends(get_current_user),
):
    """Atomic state transition with expected-state precondition.

    Founder Directive #4: prevents read-modify-write races. If DB state != expected_state, the
    update is rejected with 409 conflict.
    """
    try:
        updated = await atomic_transition(
            user_id=user["id"],
            application_id=application_id,
            expected_state=req.expected_state,
            new_state=req.new_state,
        )
    except InvalidTransition as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_transition", "from": e.from_state, "to": e.to_state,
                    "allowed_from_here": sorted(ALLOWED_TRANSITIONS.get(e.from_state, set()))},
        )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "state_precondition_failed",
                    "message": "The application's current state does not match expected_state, or it doesn't exist."},
        )
    await audit.write(user["id"], "application.transition", f"application:{application_id}",
                      {"from": req.expected_state, "to": req.new_state})
    return updated


# ========================================================================================
# Phase 4 — Prepare / Regenerate / Ready-for-approval / Resume-line accept/revert / Export
# ========================================================================================
from typing import Any  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from services import llm as llm_svc  # noqa: E402
from services import validator as validator_svc  # noqa: E402
from services.storage import storage  # noqa: E402
from services.resume_render import render_pdf, render_docx  # noqa: E402
from domains.ai_generations import service as ai_gen_svc  # noqa: E402


class RegenerateRequest(BaseModel):
    instruction: str | None = None


async def _load_approved_claims(user_id: str) -> list[dict]:
    cur = get_db().claims.find(
        {"user_id": user_id, "status": "approved", "superseded_by": None},
        {"_id": 0},
    )
    return [c async for c in cur]


async def _load_job(job_id: str) -> dict | None:
    return await get_db().jobs.find_one({"id": job_id}, {"_id": 0})


async def _run_grounded_tailoring(
    *, user_id: str, application_id: str, job: dict, instruction: str | None,
    approved_claims: list[dict],
) -> dict[str, Any]:
    """Two-attempt pipeline: try LLM, validate, one auto-regen with reasons fed back,
    then template fallback if the second attempt still fails validation.

    Returns dict with:
      final_lines: list[{text, claim_ids}]           # what to persist
      validator_result: dict                         # LAST validator outcome
      generations: list[dict]                        # ordered ai_generations rows appended
      outcome: "passed" | "template_fallback" | "refused"
      refusal: dict | None                           # if instruction was refused
    """
    generations: list[dict] = []
    refusal = None
    if instruction:
        refusal = validator_svc.refuse_instruction(instruction, approved_claims)

    # Attempt 1 — respect refusal by stripping the offending instruction phrase.
    effective_instruction = instruction if not refusal else None
    gen1 = await llm_svc.generate_tailored_lines(
        user_id=user_id, application_id=application_id,
        jd_text=job.get("jd_text") or "",
        approved_claims=approved_claims,
        instruction=effective_instruction,
    )
    vres1 = validator_svc.validate_lines(
        lines=gen1["lines"], approved_claims=approved_claims,
    )
    claims_used_1 = sorted({cid for L in gen1["lines"] for cid in (L.get("claim_ids") or [])})
    cost1 = _lookup_cost(gen1)
    row1 = await ai_gen_svc.insert(
        user_id=user_id, application_id=application_id, task="tailor_resume",
        model=gen1["model_used"], prompt_hash=gen1["prompt_hash"],
        claims_used=claims_used_1, validator_result=vres1.to_dict(),
        tokens_in_est=gen1["tokens_in_est"], tokens_out_est=gen1["tokens_out_est"],
        cost_usd_est=cost1, outcome=vres1.status, attempt_index=1,
        error=gen1.get("error"),
        instruction_hash=llm_svc._hash_prompt(effective_instruction or ""),
        refusal=refusal,
    )
    generations.append(row1)

    if vres1.status == "passed" and vres1.passed_lines:
        return {
            "final_lines": vres1.passed_lines,
            "validator_result": vres1.to_dict(),
            "generations": generations,
            "outcome": "passed",
            "refusal": refusal,
        }

    # Attempt 2 — feed rejection reasons back into the instruction
    rejection_summary = "\n".join(
        f"- Previous line rejected: {r['text'][:120]!r} — reasons: {r['reasons']}"
        for r in vres1.rejected_lines
    ) or "- Previous output produced no valid grounded lines."
    correctional_instruction = (
        (effective_instruction or "") + "\n\nCORRECTIONS REQUIRED (grounding law):\n"
        + rejection_summary
        + "\nEmit ONLY lines whose facts appear in the CLAIMS list. If you cannot ground a fact, omit it."
    ).strip()
    gen2 = await llm_svc.generate_tailored_lines(
        user_id=user_id, application_id=application_id,
        jd_text=job.get("jd_text") or "",
        approved_claims=approved_claims,
        instruction=correctional_instruction,
    )
    vres2 = validator_svc.validate_lines(
        lines=gen2["lines"], approved_claims=approved_claims,
    )
    claims_used_2 = sorted({cid for L in gen2["lines"] for cid in (L.get("claim_ids") or [])})
    cost2 = _lookup_cost(gen2)
    row2 = await ai_gen_svc.insert(
        user_id=user_id, application_id=application_id, task="tailor_resume",
        model=gen2["model_used"], prompt_hash=gen2["prompt_hash"],
        claims_used=claims_used_2, validator_result=vres2.to_dict(),
        tokens_in_est=gen2["tokens_in_est"], tokens_out_est=gen2["tokens_out_est"],
        cost_usd_est=cost2, outcome=vres2.status, attempt_index=2,
        error=gen2.get("error"),
        instruction_hash=llm_svc._hash_prompt(correctional_instruction),
        refusal=refusal,
    )
    generations.append(row2)

    if vres2.status == "passed" and vres2.passed_lines:
        return {
            "final_lines": vres2.passed_lines,
            "validator_result": vres2.to_dict(),
            "generations": generations,
            "outcome": "passed",
            "refusal": refusal,
        }

    # Both attempts failed → deterministic template fallback (NO LLM, claim-grounded)
    tmpl_lines = llm_svc.template_fallback_lines(approved_claims)
    tmpl_vres = validator_svc.validate_lines(lines=tmpl_lines, approved_claims=approved_claims)
    tmpl_row = await ai_gen_svc.insert(
        user_id=user_id, application_id=application_id, task="tailor_resume_template",
        model="template:v0.1", prompt_hash="template",
        claims_used=sorted({cid for L in tmpl_lines for cid in (L.get("claim_ids") or [])}),
        validator_result=tmpl_vres.to_dict(),
        tokens_in_est=0, tokens_out_est=0, cost_usd_est=0.0,
        outcome="template_fallback", attempt_index=3, error=None, refusal=refusal,
    )
    generations.append(tmpl_row)
    return {
        "final_lines": tmpl_vres.passed_lines,
        "validator_result": tmpl_vres.to_dict(),
        "generations": generations,
        "outcome": "template_fallback",
        "refusal": refusal,
    }


def _lookup_cost(gen: dict) -> float:
    price = llm_svc._PRICE_TABLE_PER_1K.get(gen["model_used"]) or {"in": 0.0, "out": 0.0}
    return (gen["tokens_in_est"] / 1000.0) * price["in"] + (gen["tokens_out_est"] / 1000.0) * price["out"]


def _bulletize_base(approved_claims: list[dict]) -> list[dict]:
    """Base resume — same deterministic bullet builder as template fallback."""
    return llm_svc.template_fallback_lines(approved_claims)


async def _ensure_base_manifest(user_id: str) -> list[dict]:
    """Return the current base resume manifest lines. Creates a base resume_version if none."""
    db = get_db()
    base = await db.resume_versions.find_one({"user_id": user_id, "base": True}, {"_id": 0})
    if base and (base.get("render_manifest") or {}).get("lines"):
        return base["render_manifest"]["lines"]
    approved = await _load_approved_claims(user_id)
    lines = _bulletize_base(approved)
    manifest_lines = [
        {"line_id": str(uuid.uuid4()), "text": L["text"], "claim_ids": L["claim_ids"], "status": "accepted", "base_line_ref": None}
        for L in lines
    ]
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "application_id": None,
        "name": "base",
        "base": True,
        "render_manifest": {"lines": manifest_lines},
        "s3_key": None,
        "sha256": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    await db.resume_versions.insert_one(doc)
    return manifest_lines


@router.post("/{application_id}/prepare")
async def prepare_application(
    application_id: str,
    user: dict = Depends(require_consent("generate_materials")),
):
    """Transition shortlisted → preparing, generate tailored resume, persist a tailored
    resume_version, and start the minutes_to_prepare clock.
    """
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="application_not_found")
    if app_row["state"] not in ("shortlisted", "preparing"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "state_precondition_failed", "current": app_row["state"],
                    "expected_in": ["shortlisted", "preparing"]},
        )

    job = await _load_job(app_row["job_id"])
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")

    # Atomic transition to 'preparing' if we came from 'shortlisted'
    now = utc_now()
    if app_row["state"] == "shortlisted":
        updated = await atomic_transition(
            user_id=user["id"], application_id=application_id,
            expected_state="shortlisted", new_state="preparing",
            extra_set={"prepare_started_at": now},
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail={"error": "state_precondition_failed"})
        app_row = updated

    approved = await _load_approved_claims(user["id"])
    await _ensure_base_manifest(user["id"])

    # Run the grounded pipeline
    tailoring = await _run_grounded_tailoring(
        user_id=user["id"], application_id=application_id, job=job,
        instruction=None, approved_claims=approved,
    )

    # Persist a tailored resume_version
    manifest_lines = [
        {"line_id": str(uuid.uuid4()), "text": L["text"], "claim_ids": L["claim_ids"], "status": "proposed", "base_line_ref": None}
        for L in tailoring["final_lines"]
    ]
    resume_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": application_id,
        "name": f"tailored:{app_row['job_snapshot'].get('canonical_key') or app_row['job_id']}",
        "base": False,
        "render_manifest": {
            "lines": manifest_lines,
            "validator_result": tailoring["validator_result"],
            "outcome": tailoring["outcome"],
            "generations": [g["id"] for g in tailoring["generations"]],
            "refusal": tailoring["refusal"],
        },
        "s3_key": None,
        "sha256": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.resume_versions.insert_one(resume_doc)
    await db.applications.update_one(
        {"id": application_id, "user_id": user["id"]},
        {"$set": {"materials.resume_version_id": resume_doc["id"], "updated_at": now}},
    )
    await audit.write(user["id"], "application.prepare", f"application:{application_id}",
                      {"outcome": tailoring["outcome"], "n_lines": len(manifest_lines)})

    resume_doc.pop("_id", None)
    return {
        "application": {**app_row, "state": "preparing", "prepare_started_at": now},
        "resume_version": resume_doc,
        "validator_result": tailoring["validator_result"],
        "outcome": tailoring["outcome"],
        "refusal": tailoring["refusal"],
        "generations": tailoring["generations"],
    }


@router.post("/{application_id}/regenerate")
async def regenerate_application(
    application_id: str,
    req: RegenerateRequest,
    user: dict = Depends(require_consent("generate_materials")),
):
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="application_not_found")
    if app_row["state"] not in ("preparing", "awaiting_approval"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "state_precondition_failed", "current": app_row["state"],
                    "expected_in": ["preparing", "awaiting_approval"]},
        )
    # If we were in awaiting_approval, walk back to preparing so validator status has meaning again.
    if app_row["state"] == "awaiting_approval":
        await atomic_transition(
            user_id=user["id"], application_id=application_id,
            expected_state="awaiting_approval", new_state="preparing",
        )

    job = await _load_job(app_row["job_id"])
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")

    approved = await _load_approved_claims(user["id"])
    tailoring = await _run_grounded_tailoring(
        user_id=user["id"], application_id=application_id, job=job,
        instruction=req.instruction, approved_claims=approved,
    )
    now = utc_now()
    manifest_lines = [
        {"line_id": str(uuid.uuid4()), "text": L["text"], "claim_ids": L["claim_ids"], "status": "proposed", "base_line_ref": None}
        for L in tailoring["final_lines"]
    ]
    resume_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": application_id,
        "name": f"tailored:{app_row['job_snapshot'].get('canonical_key') or app_row['job_id']}:v{int(now.timestamp())}",
        "base": False,
        "render_manifest": {
            "lines": manifest_lines,
            "validator_result": tailoring["validator_result"],
            "outcome": tailoring["outcome"],
            "generations": [g["id"] for g in tailoring["generations"]],
            "refusal": tailoring["refusal"],
        },
        "s3_key": None, "sha256": None,
        "created_at": now, "updated_at": now,
    }
    await db.resume_versions.insert_one(resume_doc)
    await db.applications.update_one(
        {"id": application_id, "user_id": user["id"]},
        {"$set": {"materials.resume_version_id": resume_doc["id"], "updated_at": now}},
    )
    await audit.write(user["id"], "application.regenerate", f"application:{application_id}",
                      {"outcome": tailoring["outcome"], "instruction_hash": llm_svc._hash_prompt(req.instruction or "")})
    resume_doc.pop("_id", None)
    return {
        "resume_version": resume_doc,
        "validator_result": tailoring["validator_result"],
        "outcome": tailoring["outcome"],
        "refusal": tailoring["refusal"],
        "generations": tailoring["generations"],
    }


class LineActionRequest(BaseModel):
    action: str  # 'accept' | 'revert'


@router.post("/{application_id}/resume-lines/{line_id}")
async def resume_line_action(
    application_id: str, line_id: str,
    req: LineActionRequest,
    user: dict = Depends(get_current_user),
):
    if req.action not in ("accept", "revert"):
        raise HTTPException(status_code=400, detail={"error": "invalid_action"})
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    resume_id = (app_row.get("materials") or {}).get("resume_version_id")
    if not resume_id:
        raise HTTPException(status_code=404, detail="no_tailored_resume")
    new_status = "accepted" if req.action == "accept" else "reverted"
    res = await db.resume_versions.update_one(
        {"id": resume_id, "user_id": user["id"], "render_manifest.lines.line_id": line_id},
        {"$set": {"render_manifest.lines.$.status": new_status, "updated_at": utc_now()}},
    )
    if not res.modified_count:
        raise HTTPException(status_code=404, detail={"error": "line_not_found"})
    resume_doc = await db.resume_versions.find_one({"id": resume_id}, {"_id": 0})
    return {"resume_version": resume_doc}


@router.post("/{application_id}/ready-for-approval")
async def ready_for_approval(
    application_id: str,
    user: dict = Depends(get_current_user),
):
    """Transition preparing → awaiting_approval + stamp minutes_to_prepare + bump apps_prepared once."""
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    # Gate: every sensitive_* screener on the job MUST have an approved answer row.
    # (Counting only screening_answers rows would let unanswered-but-required questions slip through.)
    job = await db.jobs.find_one({"id": app_row["job_id"]}, {"_id": 0, "screener_questions": 1})
    sensitive_qids: list[str] = []
    for q in (job or {}).get("screener_questions") or []:
        if q.get("kind") in ("sensitive_visa", "sensitive_salary", "sensitive_clearance"):
            sensitive_qids.append(q["id"])
    unmet: list[str] = []
    if sensitive_qids:
        answers_cur = db.screening_answers.find({
            "user_id": user["id"], "application_id": application_id,
            "question_id": {"$in": sensitive_qids},
        }, {"_id": 0, "question_id": 1, "answer": 1, "approved": 1})
        by_qid: dict[str, dict] = {}
        async for row in answers_cur:
            by_qid[row["question_id"]] = row
        for qid in sensitive_qids:
            row = by_qid.get(qid)
            if not row or not (row.get("answer") or "").strip() or not row.get("approved"):
                unmet.append(qid)
    if unmet:
        raise HTTPException(
            status_code=409,
            detail={"error": "sensitive_screener_gate",
                    "message": "Sensitive screener questions (visa/salary/clearance) must be answered AND approved before this packet can go to awaiting_approval.",
                    "unmet_question_ids": unmet},
        )
    # Idempotent bump: only credit apps_prepared if THIS transition succeeds via precondition.
    now = utc_now()
    prepare_started = app_row.get("prepare_started_at")
    extra = {}
    if prepare_started:
        try:
            delta = (now - prepare_started).total_seconds() / 60.0
            extra["minutes_to_prepare"] = round(delta, 3)
        except Exception:
            pass
    updated = await atomic_transition(
        user_id=user["id"], application_id=application_id,
        expected_state="preparing", new_state="awaiting_approval",
        extra_set=extra,
    )
    if not updated:
        raise HTTPException(status_code=409, detail={"error": "state_precondition_failed"})
    from domains.usage_meters import service as um
    await um.increment_apps_prepared(user["id"])
    await audit.write(user["id"], "application.ready_for_approval",
                      f"application:{application_id}", {"minutes_to_prepare": extra.get("minutes_to_prepare")})
    return updated


@router.get("/{application_id}/prep")
async def get_prep_packet(application_id: str, user: dict = Depends(get_current_user)):
    """Full prep packet: application row + tailored resume_version + base resume + screeners + generation history."""
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    resume_id = (app_row.get("materials") or {}).get("resume_version_id")
    tailored = await db.resume_versions.find_one({"id": resume_id}, {"_id": 0}) if resume_id else None
    base = await db.resume_versions.find_one({"user_id": user["id"], "base": True}, {"_id": 0})
    generations = await ai_gen_svc.list_for_application(application_id, user["id"])
    screeners_cur = db.screening_answers.find(
        {"user_id": user["id"], "application_id": application_id}, {"_id": 0},
    ).sort("order_hint", 1)
    screeners = [s async for s in screeners_cur]
    return {
        "application": app_row,
        "resume_version": tailored,
        "base_resume": base,
        "generations": generations,
        "screeners": screeners,
    }


@router.get("/{application_id}/export/{fmt}")
async def export_resume(
    application_id: str, fmt: str,
    user: dict = Depends(get_current_user),
):
    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail={"error": "unsupported_format"})
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    resume_id = (app_row.get("materials") or {}).get("resume_version_id")
    if not resume_id:
        raise HTTPException(status_code=404, detail="no_tailored_resume")
    resume = await db.resume_versions.find_one({"id": resume_id, "user_id": user["id"]}, {"_id": 0})
    if not resume:
        raise HTTPException(status_code=404, detail="resume_version_not_found")
    accepted_lines = [L for L in (resume.get("render_manifest") or {}).get("lines", []) if L.get("status") == "accepted"]
    if not accepted_lines:
        # Fall back to proposed lines that passed validation, so a fresh prepare can be exported
        # without the user having to click Accept on every line. UI still shows the badge.
        accepted_lines = [L for L in (resume.get("render_manifest") or {}).get("lines", []) if L.get("status") == "proposed"]
    # Resolve candidate identity from approved claims.
    approved = await _load_approved_claims(user["id"])
    ident = next((c for c in approved if c.get("type") == "identity"), None)
    contact = next((c for c in approved if c.get("type") == "contact"), None)
    name = (ident.get("value") or {}).get("name") if ident else "Candidate"
    contact_val = (contact.get("value") or {}) if contact else {}
    contact_line = " · ".join([str(v) for v in contact_val.values() if v])
    job_title = app_row["job_snapshot"].get("title") or ""
    company_name = app_row["job_snapshot"].get("company_name") or ""
    if fmt == "pdf":
        data = render_pdf(candidate_name=name, contact_line=contact_line,
                          accepted_lines=accepted_lines, job_title=job_title, company_name=company_name)
        media = "application/pdf"
    else:
        data = render_docx(candidate_name=name, contact_line=contact_line,
                           accepted_lines=accepted_lines, job_title=job_title, company_name=company_name)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    # Persist to storage for provenance / re-download
    key = f"resumes/{user['id']}/{resume['id']}.{fmt}"
    meta = await storage.put(key, data, content_type=media)
    await db.resume_versions.update_one(
        {"id": resume["id"]},
        {"$set": {f"exports.{fmt}": {**meta, "created_at": utc_now()}, "updated_at": utc_now()}},
    )
    await audit.write(user["id"], "application.export", f"application:{application_id}",
                      {"fmt": fmt, "size": meta["size"], "sha256": meta["sha256"]})
    return Response(
        content=data, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="tailored-{application_id}.{fmt}"'},
    )

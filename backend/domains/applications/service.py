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

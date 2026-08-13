from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from core.deps import require_consent
from domains.documents import service as doc_svc, repository as doc_repo
from domains.documents.service import UploadError
from services.parse_failure_classifier import (
    get_friendly_copy,
    ocr_available,
    OCR_CONFIG_REQUIRED_KEY,
)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("/resume", status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    user: dict = Depends(require_consent("process_career_data")),
):
    data = await file.read()
    try:
        result = await doc_svc.upload_resume(
            user_id=user["id"],
            filename=file.filename or "resume",
            content_type=file.content_type or "",
            data=data,
        )
    except UploadError as e:
        raise HTTPException(status_code=e.status_code, detail={"error": e.code, "message": e.message})
    return result


@router.get("/me")
async def list_my_documents(user: dict = Depends(require_consent("process_career_data"))):
    docs = await doc_repo.list_for_user(user["id"])
    return {"documents": [doc_svc._to_response(d) for d in docs]}


@router.get("/{document_id}/parse-status")
async def parse_status(document_id: str, user: dict = Depends(require_consent("process_career_data"))):
    d = await doc_repo.by_id_for_user(document_id, user["id"])
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document_not_found")
    parse_error = d.get("parse_error")
    # Phase 6 prod-UX fix (2026-08-12): attach a friendly copy envelope
    # keyed by the classifier reason slug so the UI never renders the raw
    # slug as primary text. The slug is preserved as `parse_error` for
    # support metadata. `ocr_offer` is the labeled opt-in exposed only
    # when scanned_pdf_suspected AND the deploy image has the OCR path
    # available; otherwise the button surfaces as unavailable so users
    # get an accurate expectation instead of a runtime crash.
    friendly = get_friendly_copy(parse_error) if parse_error else None
    ocr_offer = None
    if parse_error == "scanned_pdf_suspected":
        ocr_offer = {
            "available": ocr_available(),
            "label": "Try OCR — experimental, review claims extra carefully",
            "config_key": OCR_CONFIG_REQUIRED_KEY if not ocr_available() else None,
        }
    return {
        "id": d["id"],
        "parse_status": d["parse_status"],
        "parse_error": parse_error,
        "parse_error_copy": friendly,
        "parse_meta": d.get("parse_meta", {}),
        "ocr_offer": ocr_offer,
    }

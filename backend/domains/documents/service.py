import logging
import uuid
from pathlib import Path
from core.config import settings
from core.time_utils import utc_now
from services.storage import storage
from services.text_extract import extract as extract_text
from services.llm import parse_resume_text
from services.queue_stub import enqueue
from services.parse_failure_classifier import (
    classify_extract_failure,
    write_parse_failure,
    REASON_EXTRACTOR_ERROR,
    REASON_PIPELINE_ERROR,
    MIN_TEXT_CHARS_THRESHOLD,
)
from domains.documents import repository as doc_repo
from domains.claims import service as claims_svc
from domains.audit import service as audit
import hashlib

log = logging.getLogger("oppos.documents")

ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


class UploadError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def upload_resume(user_id: str, *, filename: str, content_type: str, data: bytes) -> dict:
    if content_type not in ALLOWED_TYPES:
        raise UploadError("unsupported_type", "Only PDF and DOCX files are accepted.")
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise UploadError("file_too_large", f"File exceeds the {settings.MAX_UPLOAD_MB} MB limit.", 413)
    if len(data) == 0:
        raise UploadError("empty_file", "The uploaded file is empty.")

    sha = hashlib.sha256(data).hexdigest()
    # De-dupe by sha per user — return the existing document, do not re-store.
    existing = await doc_repo.by_sha_for_user(sha, user_id)
    if existing:
        return {"document": _to_response(existing), "deduped": True}

    ext = ALLOWED_TYPES[content_type]
    doc_id = str(uuid.uuid4())
    key = f"users/{user_id}/resumes/{sha}{ext}"
    put_meta = await storage.put(key, data, content_type=content_type)
    now = utc_now()
    doc = {
        "id": doc_id,
        "user_id": user_id,
        "kind": "resume",
        "original_filename": filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "s3_key": put_meta["s3_key"],
        "sha256": put_meta["sha256"],
        "av_status": "skipped_v0.1",
        "parse_status": "queued",
        "parse_error": None,
        "parse_meta": {},
        "created_at": now,
        "updated_at": now,
    }
    await doc_repo.insert(doc)
    await audit.write(user_id, "document.upload", f"document:{doc_id}", {"kind": "resume", "sha256": sha, "size": len(data)})

    # Kick off background parse via labeled queue stub
    enqueue(lambda: _parse_pipeline(doc_id, user_id, key, content_type), name=f"resume-parse-{doc_id}")
    return {"document": _to_response(doc), "deduped": False}


async def _parse_pipeline(document_id: str, user_id: str, s3_key: str, content_type: str) -> None:
    log.info("parse start doc=%s", document_id)
    # File kind derived once, up-front — used across every telemetry write
    # so we never mislabel because of a mid-pipeline branch. Pipeline-level
    # failures (before/after the extractor) get file_kind="unknown" and
    # extractor="n/a"; classifier-classified rows carry the specific
    # extractor library that ran.
    file_kind_guess = "pdf" if "pdf" in (content_type or "").lower() else \
                        ("docx" if "docx" in (content_type or "").lower() or "wordprocessing" in (content_type or "").lower() else "unknown")
    data: bytes | None = None
    try:
        await doc_repo.update_parse_status(document_id, status="extracting")
        # Read from storage to a temporary path for the extractor libraries
        data = await storage.get(s3_key)
        tmp_path = Path(f"/tmp/oppos-resume-{document_id}")
        tmp_path.write_bytes(data)
        try:
            try:
                envelope = extract_text(tmp_path, content_type)
            except Exception as ex:
                # HOTFIX (2026-08-12): the extractor RAISED. NEVER label
                # this as "too_short" — that misdiagnosis is what caused
                # the founder's prod triage. Split: reason=extractor_error,
                # exception_class carried in telemetry only, never surfaced
                # to the user (raw traces cannot leak; the UI renders the
                # verbatim FRIENDLY_COPY for `extractor_error`).
                exception_class = type(ex).__name__
                log.warning("extractor raised doc=%s cls=%s msg=%s",
                            document_id, exception_class, str(ex)[:200])
                await write_parse_failure(
                    user_id=user_id,
                    document_id=document_id,
                    file_kind=file_kind_guess,
                    file_bytes=len(data) if data else 0,
                    extracted_chars=0,
                    reason=REASON_EXTRACTOR_ERROR,
                    pdf_num_pages=None,
                    extractor="pypdf" if file_kind_guess == "pdf" else ("python-docx" if file_kind_guess == "docx" else "n/a"),
                    exception_class=exception_class,
                )
                await doc_repo.update_parse_status(
                    document_id, status="failed", error=REASON_EXTRACTOR_ERROR,
                    meta={
                        "extractor": "pypdf" if file_kind_guess == "pdf" else ("python-docx" if file_kind_guess == "docx" else "n/a"),
                        "exception_class": exception_class,
                        "file_kind": file_kind_guess,
                        "file_bytes": len(data) if data else 0,
                    },
                )
                return
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        text = envelope["text"]
        file_kind = envelope["kind"]
        num_pages = envelope["num_pages"]
        file_bytes = envelope["file_bytes"] or len(data)
        extracted_chars = len(text.strip()) if text else 0
        if extracted_chars < MIN_TEXT_CHARS_THRESHOLD:
            reason = classify_extract_failure(
                file_kind=file_kind,
                file_bytes=file_bytes,
                extracted_chars=extracted_chars,
                pdf_num_pages=num_pages,
            )
            await write_parse_failure(
                user_id=user_id,
                document_id=document_id,
                file_kind=file_kind,
                file_bytes=file_bytes,
                extracted_chars=extracted_chars,
                reason=reason,
                pdf_num_pages=num_pages,
                extractor="pypdf" if file_kind == "pdf" else "python-docx",
            )
            await doc_repo.update_parse_status(
                document_id, status="failed", error=reason,
                meta={
                    "extracted_chars": extracted_chars,
                    "file_bytes": file_bytes,
                    "file_kind": file_kind,
                    "pdf_num_pages": num_pages,
                    "extractor": "pypdf" if file_kind == "pdf" else "python-docx",
                },
            )
            return
        await doc_repo.update_parse_status(document_id, status="parsing")
        result = await parse_resume_text(text, document_id, user_id=user_id)
        model_used = result.get("model_used")
        raw_claims = result.get("claims", [])
        # Persist as DRAFT claims (user_approved=False, status="pending", verification level 0)
        inserted = await claims_svc.insert_from_parse(
            user_id=user_id,
            document_id=document_id,
            model_used=model_used,
            parsed_claims=raw_claims,
        )
        await doc_repo.update_parse_status(
            document_id,
            status="completed",
            error=None,
            meta={
                "model_used": model_used,
                "raw_claim_count": len(raw_claims),
                "inserted_claim_count": inserted,
            },
        )
        # Base resume_versions row
        from core.db import get_db
        exists = await get_db().resume_versions.find_one({"user_id": user_id, "base": True})
        if not exists:
            await get_db().resume_versions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "name": "Base resume",
                "base": True,
                "document_id": document_id,
                "s3_key": s3_key,
                "render_manifest": {"claims": []},  # populated in Phase 4 when tailoring lands
                "created_at": utc_now(),
            })
        log.info("parse OK doc=%s model=%s claims=%d", document_id, model_used, inserted)
    except Exception as e:
        # HOTFIX (2026-08-12): the pipeline itself failed AFTER the
        # extractor call (LLM call, claims write, resume_versions insert,
        # DB error…). Historically this leaked `str(e)` into
        # `parse_error` — which surfaced raw traces to the user AND
        # contaminated support triage. Now:
        #   - parse_error → stable slug `pipeline_error`
        #   - exception class + user_id + file_kind → parse_failures
        #   - raw message logged (server-side) but never persisted on
        #     the document row.
        exception_class = type(e).__name__
        log.exception("parse failed doc=%s cls=%s", document_id, exception_class)
        try:
            await write_parse_failure(
                user_id=user_id,
                document_id=document_id,
                file_kind=file_kind_guess,
                file_bytes=len(data) if data else 0,
                extracted_chars=0,
                reason=REASON_PIPELINE_ERROR,
                pdf_num_pages=None,
                extractor="n/a",
                exception_class=exception_class,
            )
        except Exception:
            log.exception("pipeline_error telemetry write failed doc=%s", document_id)
        await doc_repo.update_parse_status(
            document_id, status="failed", error=REASON_PIPELINE_ERROR,
            meta={
                "exception_class": exception_class,
                "file_kind": file_kind_guess,
                "file_bytes": len(data) if data else 0,
            },
        )


def _to_response(d: dict) -> dict:
    keys = ("id", "kind", "original_filename", "content_type", "size_bytes", "sha256", "av_status", "parse_status", "parse_error", "parse_meta", "created_at", "updated_at")
    return {k: d.get(k) for k in keys}

"""Phase 6+ prod-UX fix — parse-failure classifier + telemetry regressions.

Locks the classifier decision boundaries, the telemetry write shape,
the friendly-copy contract per reason slug, and the OCR opt-in stub
(CONFIGURATION_REQUIRED on the current deploy image).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client_per_test():
    """Motor caches its AsyncIOMotorClient at first `get_db()` call bound
    to that loop; pytest-asyncio makes a fresh loop per async test. Reset
    before every test so `get_db()` re-binds. Same pattern as
    `tests/test_credits_ledger.py`.
    """
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield

from services.parse_failure_classifier import (
    classify_extract_failure,
    write_parse_failure,
    get_friendly_copy,
    ocr_available,
    try_ocr_pdf,
    REASON_SCANNED_PDF_SUSPECTED,
    REASON_TOO_LITTLE_CONTENT,
    REASON_DOCX_EXTRACTOR_BLIND,
    REASON_EXTRACTOR_ERROR,
    REASON_PIPELINE_ERROR,
    REASON_EXTRACT_FAILED,  # legacy alias — still importable
    OCR_CONFIG_REQUIRED_KEY,
    MIN_TEXT_CHARS_THRESHOLD,
    DOCX_EXTRACTOR_BLIND_MIN_BYTES,
)
from services.text_extract import extract_pdf


FIXTURE_SCANNED_PDF = Path(__file__).parent / "fixtures" / "scanned_resume_sample.pdf"


# --------------------------------------------------------------------
# Classifier decision boundaries
# --------------------------------------------------------------------

def test_classifier_scanned_pdf_zero_chars_large_file():
    """Founder's real prod repro: 1666KB PDF, 0 extracted chars, 1+ pages."""
    reason = classify_extract_failure(
        file_kind="pdf",
        file_bytes=1_666_000,
        extracted_chars=0,
        pdf_num_pages=2,
    )
    assert reason == REASON_SCANNED_PDF_SUSPECTED


def test_classifier_scanned_pdf_tiny_bytes_falls_back_to_thin():
    """A tiny PDF with 0 chars isn't confidently scanned; treat as thin."""
    reason = classify_extract_failure(
        file_kind="pdf",
        file_bytes=8_000,
        extracted_chars=0,
        pdf_num_pages=1,
    )
    assert reason == REASON_TOO_LITTLE_CONTENT


def test_classifier_docx_never_scanned():
    """DOCX doesn't have an image-only mode we can classify from bytes;
    plausibly-sized DOCX with ~no text is `docx_extractor_blind` (text
    lives in text boxes / headers / footers — python-docx can't see it).
    Hotfix (2026-08-12) — this reason WAS the founder's real prod bug
    class, previously mislabeled as `extracted_text_too_short`."""
    reason = classify_extract_failure(
        file_kind="docx",
        file_bytes=2_000_000,
        extracted_chars=5,
        pdf_num_pages=None,
    )
    assert reason == REASON_DOCX_EXTRACTOR_BLIND


def test_classifier_tiny_docx_is_thin_not_blind():
    """A DOCX under DOCX_EXTRACTOR_BLIND_MIN_BYTES is genuinely empty."""
    reason = classify_extract_failure(
        file_kind="docx",
        file_bytes=DOCX_EXTRACTOR_BLIND_MIN_BYTES - 1,
        extracted_chars=5,
        pdf_num_pages=None,
    )
    assert reason == REASON_TOO_LITTLE_CONTENT


def test_reason_extract_failed_is_alias_for_extractor_error():
    """Legacy naming — kept importable so historic parse_failures rows
    with reason='extract_failed' remain discoverable in ledger queries."""
    assert REASON_EXTRACT_FAILED == REASON_EXTRACTOR_ERROR
    assert REASON_EXTRACTOR_ERROR == "extractor_error"


def test_classifier_high_bytes_per_char_ratio_pdf_is_scanned():
    """A large PDF with only a handful of chars is scanned (ratio heuristic)."""
    reason = classify_extract_failure(
        file_kind="pdf",
        file_bytes=800_000,
        extracted_chars=10,  # 80,000 bytes/char
        pdf_num_pages=3,
    )
    assert reason == REASON_SCANNED_PDF_SUSPECTED


def test_classifier_natively_thin_pdf_is_not_scanned():
    """Small PDF with a few sentences of extracted text = thin, not scanned."""
    reason = classify_extract_failure(
        file_kind="pdf",
        file_bytes=45_000,
        extracted_chars=20,  # 2250 bytes/char, under heuristic
        pdf_num_pages=1,
    )
    assert reason == REASON_TOO_LITTLE_CONTENT


def test_min_text_chars_threshold_boundary_locked():
    """Guard the threshold constant so future edits require a coordinated
    UI/copy change."""
    assert MIN_TEXT_CHARS_THRESHOLD == 30


# --------------------------------------------------------------------
# Real fixture: image-only PDF flows through the extractor + classifier
# --------------------------------------------------------------------

def test_fixture_scanned_pdf_extracts_to_zero_chars_and_classifies_as_scanned():
    """The tests/fixtures/scanned_resume_sample.pdf is an image-only PDF
    generated with ReportLab. `pypdf.extract_text` returns empty; the
    classifier calls it scanned_pdf_suspected."""
    assert FIXTURE_SCANNED_PDF.exists(), (
        "Fixture scanned_resume_sample.pdf missing — regenerate with the "
        "recipe in docs/PHASE-6-EVIDENCE.md §parse_failure."
    )
    env = extract_pdf(FIXTURE_SCANNED_PDF)
    assert env["kind"] == "pdf"
    assert env["num_pages"] == 1
    assert env["file_bytes"] > 100_000, f"expected >100KB, got {env['file_bytes']}"
    extracted_chars = len(env["text"].strip())
    assert extracted_chars < MIN_TEXT_CHARS_THRESHOLD, (
        f"expected fixture to extract <{MIN_TEXT_CHARS_THRESHOLD} chars, got {extracted_chars}"
    )
    reason = classify_extract_failure(
        file_kind=env["kind"],
        file_bytes=env["file_bytes"],
        extracted_chars=extracted_chars,
        pdf_num_pages=env["num_pages"],
    )
    assert reason == REASON_SCANNED_PDF_SUSPECTED


# --------------------------------------------------------------------
# Friendly-copy contract
# --------------------------------------------------------------------

def test_friendly_copy_scanned_pdf_contains_founder_verbatim_message():
    """Verbatim per the founder's directive."""
    c = get_friendly_copy(REASON_SCANNED_PDF_SUSPECTED)
    assert "scanned or image-based" in c["headline"]
    assert "DOCX" in c["body"]
    assert "Word" in c["body"] and "Google Docs" in c["body"]
    assert c["tip"] and "select text" in c["tip"]
    assert c["cta"]


def test_friendly_copy_too_little_content_is_distinct_from_scanned():
    c = get_friendly_copy(REASON_TOO_LITTLE_CONTENT)
    body_l = c["body"].lower()
    # Must NOT say "scanned" (that's the scanned-pdf copy) and must
    # direct the user to add content rather than re-export.
    assert "scanned" not in c["headline"].lower()
    assert "add" in body_l  # "Add your experience..."
    assert c["cta"]


def test_friendly_copy_extract_failed_shape():
    c = get_friendly_copy(REASON_EXTRACTOR_ERROR)
    assert c["headline"] and c["body"] and c["cta"]


def test_friendly_copy_docx_extractor_blind_shape():
    """Hotfix (2026-08-12) — the DOCX-blind copy MUST NOT be the
    generic thin-content message ('add more content'). The DOCX has
    content; python-docx just can't see it. Copy must direct the user
    to re-save from Word/Google Docs."""
    c = get_friendly_copy(REASON_DOCX_EXTRACTOR_BLIND)
    assert c["headline"] and c["body"] and c["cta"]
    assert "text boxes" in c["body"] or "headers" in c["body"]
    assert "add" not in c["body"].lower() or "save as" in c["body"].lower()


def test_friendly_copy_pipeline_error_shape():
    """Hotfix (2026-08-12) — pipeline_error frames the failure as
    'our side, not your file' so users don't retry the same file
    forever thinking they need to fix it."""
    c = get_friendly_copy(REASON_PIPELINE_ERROR)
    assert c["headline"] and c["body"] and c["cta"]
    assert "our side" in c["body"] or "issue on our" in c["body"]


def test_friendly_copy_unknown_slug_falls_back_to_thin_never_raw():
    """A future slug we don't know about must never surface as raw text
    to the user — default to the thin-content copy."""
    c = get_friendly_copy("some_future_slug_we_dont_know")
    assert c["headline"]  # not empty
    assert "some_future_slug" not in c["headline"]
    assert "some_future_slug" not in c["body"]


# --------------------------------------------------------------------
# Telemetry write shape
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telemetry_row_written_with_full_shape():
    """`parse_failures` row is append-only and carries the founder's
    required fields (2026-08-12 P0 hotfix): {user_id, file_kind, bytes,
    extracted_chars, extractor, reason, exception_class?, ts} — plus
    document_id + pdf_num_pages + id for internal audit."""
    from core.db import get_db
    db = get_db()
    uid = f"parse-tele-{uuid.uuid4().hex[:12]}"
    did = f"doc-{uuid.uuid4().hex[:12]}"
    row_id = await write_parse_failure(
        user_id=uid,
        document_id=did,
        file_kind="pdf",
        file_bytes=1_666_000,
        extracted_chars=0,
        reason=REASON_SCANNED_PDF_SUSPECTED,
        pdf_num_pages=2,
        extractor="pypdf",
    )
    assert row_id
    row = await db.parse_failures.find_one({"id": row_id}, {"_id": 0})
    assert row is not None
    assert row["user_id"] == uid
    assert row["document_id"] == did
    assert row["file_kind"] == "pdf"
    assert row["bytes"] == 1_666_000
    assert row["extracted_chars"] == 0
    assert row["reason"] == REASON_SCANNED_PDF_SUSPECTED
    assert row["pdf_num_pages"] == 2
    assert row["extractor"] == "pypdf"
    assert row["exception_class"] is None
    assert row["ts"] is not None


@pytest.mark.asyncio
async def test_telemetry_extractor_error_carries_exception_class():
    """Hotfix (2026-08-12) — the founder's directive: on extractor
    exception, exception_class MUST be in telemetry, and NEVER surface
    a raw trace to the user."""
    from core.db import get_db
    db = get_db()
    uid = f"parse-tele-{uuid.uuid4().hex[:12]}"
    did = f"doc-{uuid.uuid4().hex[:12]}"
    row_id = await write_parse_failure(
        user_id=uid,
        document_id=did,
        file_kind="pdf",
        file_bytes=250_000,
        extracted_chars=0,
        reason=REASON_EXTRACTOR_ERROR,
        pdf_num_pages=None,
        extractor="pypdf",
        exception_class="PdfReadError",
    )
    row = await db.parse_failures.find_one({"id": row_id}, {"_id": 0})
    assert row["reason"] == REASON_EXTRACTOR_ERROR
    assert row["extractor"] == "pypdf"
    assert row["exception_class"] == "PdfReadError"


@pytest.mark.asyncio
async def test_telemetry_pipeline_error_extractor_na():
    """Hotfix (2026-08-12) — outer catch (LLM error, DB error, etc.)
    writes reason=pipeline_error with extractor='n/a'; the extractor
    field distinguishes 'library failed' from 'downstream failed' when
    triaging."""
    from core.db import get_db
    db = get_db()
    uid = f"parse-tele-{uuid.uuid4().hex[:12]}"
    did = f"doc-{uuid.uuid4().hex[:12]}"
    row_id = await write_parse_failure(
        user_id=uid,
        document_id=did,
        file_kind="docx",
        file_bytes=45_000,
        extracted_chars=0,
        reason=REASON_PIPELINE_ERROR,
        extractor="n/a",
        exception_class="ConnectionError",
    )
    row = await db.parse_failures.find_one({"id": row_id}, {"_id": 0})
    assert row["reason"] == REASON_PIPELINE_ERROR
    assert row["extractor"] == "n/a"
    assert row["exception_class"] == "ConnectionError"


# --------------------------------------------------------------------
# HOTFIX (2026-08-12) — end-to-end pipeline exception path
# Locks: an exception in extract_text() results in
# parse_status="failed", parse_error="extractor_error" (NEVER
# "extracted_text_too_short"), plus a telemetry row with
# exception_class. The founder's directive: mislabeled errors caused
# the prod triage — make them impossible going forward.
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_labels_extractor_exception_as_extractor_error_not_too_short(monkeypatch):
    """When `text_extract.extract` raises (any exception, not just
    RuntimeError), the pipeline writes:
      - parse_status='failed'
      - parse_error='extractor_error'  ← NEVER 'too_short' or similar
      - parse_failures row with reason=extractor_error + exception_class
    """
    from core.db import get_db
    from services.storage import storage
    from domains.documents import service as doc_svc
    from domains.documents import repository as doc_repo

    db = get_db()
    uid = f"pipe-e2e-{uuid.uuid4().hex[:12]}"
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    # Materialize a document row so update_parse_status has something to update.
    now_iso = "2026-08-12T00:00:00+00:00"
    await db.documents.insert_one({
        "id": doc_id,
        "user_id": uid,
        "kind": "resume",
        "original_filename": "broken.pdf",
        "content_type": "application/pdf",
        "size_bytes": 250_000,
        "s3_key": f"users/{uid}/resumes/broken.pdf",
        "sha256": "x" * 64,
        "av_status": "skipped_v0.1",
        "parse_status": "queued",
        "parse_error": None,
        "parse_meta": {},
        "created_at": now_iso,
        "updated_at": now_iso,
    })

    # Stub storage.get to return non-empty bytes so we exercise the
    # extractor branch, not the storage-failure branch.
    async def fake_get(key: str) -> bytes:  # noqa: ARG001
        return b"%PDF-1.0 dummy bytes " * 5000  # ~100KB of garbage
    monkeypatch.setattr(storage, "get", fake_get)

    # Force the extractor to raise a NON-RuntimeError so we prove the
    # broadened `except Exception` inner catch is in place — this was
    # the exact class of bug the founder's directive is closing.
    from services import text_extract
    def boom(_path, _mime):
        raise ValueError("simulated_pypdf_regression")
    monkeypatch.setattr(text_extract, "extract", boom)
    monkeypatch.setattr("domains.documents.service.extract_text", boom)

    await doc_svc._parse_pipeline(  # type: ignore[attr-defined]
        document_id=doc_id,
        user_id=uid,
        s3_key=f"users/{uid}/resumes/broken.pdf",
        content_type="application/pdf",
    )

    d = await doc_repo.by_id_for_user(doc_id, uid)
    assert d["parse_status"] == "failed"
    assert d["parse_error"] == REASON_EXTRACTOR_ERROR, (
        f"expected reason='extractor_error', got '{d['parse_error']}' — "
        "mislabeled errors are the founder's prod triage bug class"
    )
    # No raw trace / message leaks into the document row.
    meta = d.get("parse_meta") or {}
    assert "simulated_pypdf_regression" not in str(meta)
    assert meta.get("exception_class") == "ValueError"
    # Telemetry row written with exception_class.
    tele = await db.parse_failures.find_one({"document_id": doc_id}, {"_id": 0})
    assert tele is not None
    assert tele["reason"] == REASON_EXTRACTOR_ERROR
    assert tele["exception_class"] == "ValueError"
    assert tele["extractor"] == "pypdf"


@pytest.mark.asyncio
async def test_pipeline_outer_error_uses_pipeline_error_slug_not_raw_string(monkeypatch):
    """When the pipeline fails AFTER extraction (e.g., LLM call raises),
    the outer catch must set parse_error='pipeline_error' — NEVER a
    raw exception string that would surface to the user."""
    from core.db import get_db
    from services.storage import storage
    from services import llm as llm_service
    from domains.documents import service as doc_svc
    from domains.documents import repository as doc_repo

    db = get_db()
    uid = f"pipe-outer-{uuid.uuid4().hex[:12]}"
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    now_iso = "2026-08-12T00:00:00+00:00"
    await db.documents.insert_one({
        "id": doc_id, "user_id": uid, "kind": "resume",
        "original_filename": "ok.docx",
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size_bytes": 40000, "s3_key": f"users/{uid}/resumes/ok.docx",
        "sha256": "y" * 64, "av_status": "skipped_v0.1",
        "parse_status": "queued", "parse_error": None, "parse_meta": {},
        "created_at": now_iso, "updated_at": now_iso,
    })

    async def fake_get(key: str) -> bytes:  # noqa: ARG001
        return b"docx bytes"
    monkeypatch.setattr(storage, "get", fake_get)
    # Make extraction succeed with plenty of content.
    def fake_extract(_p, _mime):
        return {"text": "Plenty of content here. " * 100, "kind": "docx",
                "num_pages": None, "file_bytes": 40000}
    monkeypatch.setattr("domains.documents.service.extract_text", fake_extract)
    # Now make the LLM step raise a CRAZY_LEAKING_MESSAGE.
    async def boom(*args, **kwargs):  # noqa: ARG001
        raise ConnectionError("CRAZY_LEAKING_MESSAGE_TOKEN_do_not_show_users")
    monkeypatch.setattr(llm_service, "parse_resume_text", boom)
    monkeypatch.setattr("domains.documents.service.parse_resume_text", boom)

    await doc_svc._parse_pipeline(  # type: ignore[attr-defined]
        document_id=doc_id, user_id=uid,
        s3_key=f"users/{uid}/resumes/ok.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    d = await doc_repo.by_id_for_user(doc_id, uid)
    assert d["parse_status"] == "failed"
    assert d["parse_error"] == REASON_PIPELINE_ERROR
    # Raw exception message must not leak.
    assert "CRAZY_LEAKING_MESSAGE_TOKEN" not in str(d.get("parse_meta") or {})
    assert "CRAZY_LEAKING_MESSAGE_TOKEN" not in (d.get("parse_error") or "")
    # Telemetry carries the exception class name.
    tele = await db.parse_failures.find_one({"document_id": doc_id}, {"_id": 0})
    assert tele is not None
    assert tele["reason"] == REASON_PIPELINE_ERROR
    assert tele["exception_class"] == "ConnectionError"
    assert tele["extractor"] == "n/a"


# --------------------------------------------------------------------
# OCR opt-in path — CONFIGURATION_REQUIRED on the current deploy image
# --------------------------------------------------------------------

def test_ocr_available_probe_returns_false_on_current_deploy_image():
    """Documents the current state — flips to True only when tesseract
    + poppler-utils + pytesseract + pdf2image are all present."""
    assert ocr_available() is False, (
        "OCR availability probe returned True — coordinated docs update "
        "required in PHASE-6-EVIDENCE.md §parse_failure OCR section."
    )


@pytest.mark.asyncio
async def test_ocr_try_raises_configuration_required_on_current_deploy_image():
    """The stub raises NotImplementedError with the config key so callers
    can distinguish 'not available' from 'ran but returned nothing'."""
    with pytest.raises(NotImplementedError) as exc:
        await try_ocr_pdf(b"fake-pdf-bytes")
    assert OCR_CONFIG_REQUIRED_KEY in str(exc.value)


def test_ocr_config_key_is_stable_string():
    """The config key is part of the API contract with the frontend; lock it."""
    assert OCR_CONFIG_REQUIRED_KEY == "ocr_configuration_required"

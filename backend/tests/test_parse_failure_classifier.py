"""Phase 6+ prod-UX fix — parse-failure classifier + telemetry regressions.

Locks the classifier decision boundaries, the telemetry write shape,
the friendly-copy contract per reason slug, and the OCR opt-in stub
(CONFIGURATION_REQUIRED on the current deploy image).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from services.parse_failure_classifier import (
    classify_extract_failure,
    write_parse_failure,
    get_friendly_copy,
    ocr_available,
    try_ocr_pdf,
    REASON_SCANNED_PDF_SUSPECTED,
    REASON_TOO_LITTLE_CONTENT,
    REASON_EXTRACT_FAILED,
    OCR_CONFIG_REQUIRED_KEY,
    MIN_TEXT_CHARS_THRESHOLD,
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
    """DOCX doesn't have an image-only mode we can classify from bytes."""
    reason = classify_extract_failure(
        file_kind="docx",
        file_bytes=2_000_000,
        extracted_chars=5,
        pdf_num_pages=None,
    )
    assert reason == REASON_TOO_LITTLE_CONTENT


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
    assert "very little text" in c["body"].lower()
    assert "scanned" not in c["headline"].lower()
    assert c["cta"]


def test_friendly_copy_extract_failed_shape():
    c = get_friendly_copy(REASON_EXTRACT_FAILED)
    assert c["headline"] and c["body"] and c["cta"]


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
    required fields: {user_id, file_kind, bytes, extracted_chars, reason, ts}."""
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
    assert row["ts"] is not None


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

"""Parse-failure classifier + telemetry (Phase 6+ prod UX fix, 2026-08-12).

Distinguishes scanned/image-based PDFs (no text layer) from genuinely-thin
text documents so the UI can surface accurate recovery guidance instead of
raw slugs, and writes structured `parse_failures` rows for measuring
failure classes (feeds `/standards` later).

Rails:
- Detection is READ-ONLY on the extracted text + PDF metadata; no
  external network calls, no OCR by default. The OCR opt-in path is
  wrapped by `try_ocr_pdf` which is stubbed here as
  CONFIGURATION_REQUIRED — tesseract + poppler-utils are absent from
  the current deploy image (verified 2026-08-12).
- Classifier is deterministic (pure function on inputs); no LLM,
  no heuristics beyond page-count / char-count ratios.
- Telemetry rows are append-only (`parse_failures` collection); no user
  content is stored, only file kind + byte counts + reason.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from core.db import get_db
from core.time_utils import utc_now

log = logging.getLogger("oppos.parse_failure_classifier")

# Threshold: if extracted text is <30 chars AND we can see ≥1 page in the
# PDF AND the file is >100KB, we treat this as a scanned/image-based PDF.
# Threshold was chosen to match the founder's real prod failure:
# a 1666KB PDF with 0 chars extracted → clearly image-based.
MIN_TEXT_CHARS_THRESHOLD = 30
SCANNED_PDF_MIN_BYTES = 100 * 1024        # <100KB image PDFs are unusual
SCANNED_PDF_MIN_PAGES = 1
SCANNED_PDF_BYTES_PER_CHAR_HEURISTIC = 5000  # bytes / extracted_chars

# Reason slugs — stable identifiers written to parse_failures.reason.
REASON_SCANNED_PDF_SUSPECTED = "scanned_pdf_suspected"
REASON_TOO_LITTLE_CONTENT = "too_little_content"
REASON_EXTRACT_FAILED = "extract_failed"


# Friendly copy shown to users (verbatim; the raw slug is small-print
# support metadata). Locked to a small, deterministic surface so the UI
# can trust them by reason key.
FRIENDLY_COPY: dict[str, dict[str, str]] = {
    REASON_SCANNED_PDF_SUSPECTED: {
        "headline": "This PDF looks scanned or image-based",
        "body": "We can't read pictures of text. Upload the original DOCX, "
                "or re-export a PDF from Word or Google Docs.",
        "tip": "Tip: if you can't select text in your PDF, neither can we.",
        "cta": "Upload a different file",
    },
    REASON_TOO_LITTLE_CONTENT: {
        "headline": "This résumé has very little text",
        "body": "There isn't enough content on the page for us to build a "
                "reliable Passport from. Add your experience and skills, or "
                "upload a fuller version.",
        "tip": None,
        "cta": "Upload a different file",
    },
    REASON_EXTRACT_FAILED: {
        "headline": "We couldn't open this file",
        "body": "The file may be corrupt or password-protected. Try "
                "re-exporting it, or upload a DOCX instead.",
        "tip": None,
        "cta": "Upload a different file",
    },
}


def classify_extract_failure(
    *,
    file_kind: str,
    file_bytes: int,
    extracted_chars: int,
    pdf_num_pages: Optional[int] = None,
) -> str:
    """Return one of the REASON_ slugs describing why extraction fell
    below the usable threshold.

    - PDFs with 0 or very few chars but non-trivial byte size and at
      least one page → `scanned_pdf_suspected` (opt-in OCR could help).
    - Anything else (thin DOCX, thin natively-text PDF) →
      `too_little_content` (user should add more content).
    """
    kind = (file_kind or "").lower()
    if kind == "pdf" and pdf_num_pages and pdf_num_pages >= SCANNED_PDF_MIN_PAGES:
        # High bytes-per-char ratio → we got lots of PDF but ~no text →
        # image-based / scanned. Also handles the extracted_chars=0 case.
        if extracted_chars == 0 and file_bytes >= SCANNED_PDF_MIN_BYTES:
            return REASON_SCANNED_PDF_SUSPECTED
        if extracted_chars > 0:
            bytes_per_char = file_bytes / max(extracted_chars, 1)
            if bytes_per_char >= SCANNED_PDF_BYTES_PER_CHAR_HEURISTIC and file_bytes >= SCANNED_PDF_MIN_BYTES:
                return REASON_SCANNED_PDF_SUSPECTED
    return REASON_TOO_LITTLE_CONTENT


async def write_parse_failure(
    *,
    user_id: str,
    document_id: str,
    file_kind: str,
    file_bytes: int,
    extracted_chars: int,
    reason: str,
    pdf_num_pages: Optional[int] = None,
) -> str:
    """Append a `parse_failures` row for offline analysis. Never fails
    the parse pipeline — logs and swallows exceptions."""
    row_id = str(uuid.uuid4())
    doc = {
        "id": row_id,
        "user_id": user_id,
        "document_id": document_id,
        "file_kind": file_kind,
        "bytes": int(file_bytes),
        "extracted_chars": int(extracted_chars),
        "pdf_num_pages": pdf_num_pages,
        "reason": reason,
        "ts": utc_now(),
    }
    try:
        await get_db().parse_failures.insert_one(doc)
    except Exception:
        log.exception("parse_failures write failed doc=%s", document_id)
    return row_id


def get_friendly_copy(reason: str) -> dict:
    """Return the {headline, body, tip, cta} tuple for a given reason.

    Callers should render this verbatim; the raw slug is separately
    surfaced as small-print support metadata. Defaults to the
    `too_little_content` copy if the reason is unknown so we never
    show a raw slug to the user.
    """
    return FRIENDLY_COPY.get(reason, FRIENDLY_COPY[REASON_TOO_LITTLE_CONTENT])


# --------------------------------------------------------------------
# OCR opt-in path — CONFIGURATION_REQUIRED (2026-08-12)
# --------------------------------------------------------------------
#
# The deploy image currently lacks `tesseract-ocr` (system binary) and
# `poppler-utils` (`pdftoppm` / `pdfinfo`) as well as the `pytesseract`
# and `pdf2image` Python modules. Verified on the preview pod: `which
# tesseract` → not found; `pip show pytesseract` → not installed. The
# founder's rail is "verify it would survive the production deploy,
# not just the dev pod" — so we DO NOT ship an unstable OCR path.
#
# This stub is the interface boundary. Enabling OCR is a coordinated
# deploy-image change: add `tesseract-ocr` (+ `tesseract-ocr-eng`),
# `poppler-utils` (Dockerfile apt install) and `pytesseract` +
# `pdf2image` (requirements.txt). Once those land, replace the
# `NotImplementedError` below with the actual conversion + tesseract
# call. Every claim extracted from OCR MUST remain user-attested
# (never silent-approved), and the UI must render the experimental
# label documented in the router.
# --------------------------------------------------------------------
OCR_CONFIG_REQUIRED_KEY = "ocr_configuration_required"


def ocr_available() -> bool:
    """Runtime probe. Returns False on the current deploy image."""
    try:
        import pytesseract  # noqa: F401
        import pdf2image    # noqa: F401
    except Exception:
        return False
    # Also check the system binary is on PATH.
    import shutil
    return bool(shutil.which("tesseract")) and bool(shutil.which("pdftoppm"))


async def try_ocr_pdf(pdf_bytes: bytes) -> str:  # noqa: ARG001
    """Explicit opt-in OCR attempt. Returns the extracted text.

    CURRENTLY DISABLED: raises `NotImplementedError` with the
    `ocr_configuration_required` key. The router surfaces this to
    the UI as an unavailable button rather than a runtime crash.
    """
    if not ocr_available():
        raise NotImplementedError(OCR_CONFIG_REQUIRED_KEY)
    # Guarded reference implementation — untested on the current
    # deploy image; kept behind the availability probe so it can be
    # activated by a Dockerfile change alone.
    from pdf2image import convert_from_bytes  # type: ignore
    import pytesseract  # type: ignore
    pages = convert_from_bytes(pdf_bytes, dpi=200)
    text_parts = []
    for page in pages:
        text_parts.append(pytesseract.image_to_string(page))
    return "\n".join(text_parts).strip()

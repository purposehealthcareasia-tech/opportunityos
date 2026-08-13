"""Text extraction for résumé uploads.

Deliberately dumb: extract plain text and hand it to the LLM. No parsing heuristics here.
"""
import logging
from pathlib import Path
from typing import Optional, TypedDict
from pypdf import PdfReader
from docx import Document as DocxDocument

log = logging.getLogger("oppos.text_extract")

MAX_TEXT_CHARS = 200_000  # safety cap before LLM


class ExtractResult(TypedDict):
    """Return envelope for the extractor — text + metadata for the
    parse-failure classifier (num_pages, bytes seen, kind).
    """
    text: str
    kind: str            # "pdf" | "docx"
    num_pages: Optional[int]   # populated for PDFs, None for DOCX
    file_bytes: int      # size of the file on disk (post-decrypt)


def extract_pdf(path: str | Path) -> ExtractResult:
    p = Path(path)
    file_bytes = p.stat().st_size if p.exists() else 0
    try:
        reader = PdfReader(str(p))
        parts: list[str] = []
        num_pages = len(reader.pages)
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as e:
                log.warning("page %d extract failed: %s", i, e)
        text = "\n".join(pt for pt in parts if pt).strip()
        return {
            "text": text[:MAX_TEXT_CHARS],
            "kind": "pdf",
            "num_pages": num_pages,
            "file_bytes": file_bytes,
        }
    except Exception as e:
        raise RuntimeError(f"pdf_extract_failed: {e}")


def extract_docx(path: str | Path) -> ExtractResult:
    p = Path(path)
    file_bytes = p.stat().st_size if p.exists() else 0
    try:
        doc = DocxDocument(str(p))
        parts: list[str] = []
        for para in doc.paragraphs:
            if para.text:
                parts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text:
                        parts.append(cell.text)
        text = "\n".join(parts).strip()
        return {
            "text": text[:MAX_TEXT_CHARS],
            "kind": "docx",
            "num_pages": None,
            "file_bytes": file_bytes,
        }
    except Exception as e:
        raise RuntimeError(f"docx_extract_failed: {e}")


def extract(path: str | Path, mime: str) -> ExtractResult:
    mime = (mime or "").lower()
    p = Path(path)
    if mime == "application/pdf" or p.suffix.lower() == ".pdf":
        return extract_pdf(p)
    if mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword") or p.suffix.lower() == ".docx":
        return extract_docx(p)
    raise RuntimeError("unsupported_document_type")

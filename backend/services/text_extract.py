"""Text extraction for résumé uploads.

Deliberately dumb: extract plain text and hand it to the LLM. No parsing heuristics here.
"""
import logging
from pathlib import Path
from pypdf import PdfReader
from docx import Document as DocxDocument

log = logging.getLogger("oppos.text_extract")

MAX_TEXT_CHARS = 200_000  # safety cap before LLM


def extract_pdf(path: str | Path) -> str:
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as e:
                log.warning("page %d extract failed: %s", i, e)
        text = "\n".join(p for p in parts if p).strip()
        return text[:MAX_TEXT_CHARS]
    except Exception as e:
        raise RuntimeError(f"pdf_extract_failed: {e}")


def extract_docx(path: str | Path) -> str:
    try:
        doc = DocxDocument(str(path))
        parts: list[str] = []
        for p in doc.paragraphs:
            if p.text:
                parts.append(p.text)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text:
                        parts.append(cell.text)
        text = "\n".join(parts).strip()
        return text[:MAX_TEXT_CHARS]
    except Exception as e:
        raise RuntimeError(f"docx_extract_failed: {e}")


def extract(path: str | Path, mime: str) -> str:
    mime = (mime or "").lower()
    p = Path(path)
    if mime == "application/pdf" or p.suffix.lower() == ".pdf":
        return extract_pdf(p)
    if mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword") or p.suffix.lower() == ".docx":
        return extract_docx(p)
    raise RuntimeError("unsupported_document_type")

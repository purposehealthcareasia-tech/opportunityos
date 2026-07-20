"""Deterministic resume renderer — PDF + DOCX from accepted tailored lines.

Uses reportlab (PDF) and python-docx (DOCX) — both already installed. Output is stored
via StorageService (S3-compatible interface backed by local disk under /app/backend/storage).

Layout is intentionally plain. This is Phase 4: prove the pipeline works end-to-end; a
designer-tuned layout comes later.
"""
from __future__ import annotations
import io
from typing import Iterable

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from docx import Document


def render_pdf(
    *,
    candidate_name: str,
    contact_line: str,
    accepted_lines: Iterable[dict],
    job_title: str,
    company_name: str,
) -> bytes:
    """Build a plain-text-style résumé PDF. Returns raw bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=16, spaceAfter=6, textColor="#333333")
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10.5, leading=14)
    story = [
        Paragraph(candidate_name or "Candidate", h1),
        Paragraph(contact_line or "", body),
        Paragraph(f"Tailored for {job_title} @ {company_name}", h2),
    ]
    for L in accepted_lines:
        story.append(Paragraph("• " + (L.get("text") or ""), body))
        story.append(Spacer(1, 4))
    doc.build(story)
    return buf.getvalue()


def render_docx(
    *,
    candidate_name: str,
    contact_line: str,
    accepted_lines: Iterable[dict],
    job_title: str,
    company_name: str,
) -> bytes:
    """Build a plain-text-style résumé DOCX. Returns raw bytes."""
    doc = Document()
    doc.add_heading(candidate_name or "Candidate", level=1)
    if contact_line:
        doc.add_paragraph(contact_line)
    doc.add_heading(f"Tailored for {job_title} @ {company_name}", level=2)
    for L in accepted_lines:
        doc.add_paragraph((L.get("text") or ""), style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

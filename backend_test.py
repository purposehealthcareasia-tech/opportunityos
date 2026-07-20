"""
OpportunityOS Phase 2 — Backend verification suite.

Verifies Career Passport, Preferences, Eligibility, Gate Engine, and real-LLM
resume-parse pipeline against the preview ingress. Reuses the Phase-1 checks
but adds the Phase-2 acceptance criteria enumerated in the review request.

Base URL: from constant BASE below.
Mongo: mongodb://localhost:27017 db=opportunityos (direct probes for
       seed integrity + ledger assertions).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
import time
import uuid
from typing import Any

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from docx import Document as DocxDocument
from reportlab.pdfgen import canvas as pdf_canvas

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE = "https://af7cc636-8506-4548-af82-a1a50aae0158.preview.emergentagent.com"
API = f"{BASE}/api"
V1 = f"{API}/v1"

USER_ZERO = ("ujjwal@opportunityos.dev", "Passport!Test0")
ADMIN = ("admin@opportunityos.dev", "Admin!Console1")
SUPPORT = ("support@opportunityos.dev", "Support!Console1")

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "opportunityos"

RESULTS: list[tuple[str, bool, str]] = []


def _record(name: str, ok: bool, evidence: str) -> None:
    RESULTS.append((name, ok, evidence))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name} — {evidence}")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    r = await client.post(f"{V1}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()


async def _signup(client: httpx.AsyncClient, *, email: str, password: str, name: str,
                  process_career: bool = True, discover_jobs: bool = False) -> dict:
    body = {
        "email": email,
        "password": password,
        "name": name,
        "consents": {
            "process_career_data": process_career,
            "discover_jobs": discover_jobs,
            "generate_materials": False,
            "track_applications": False,
            "email_me": False,
        },
        "policy_text_version": "1.0",
    }
    r = await client.post(f"{V1}/auth/signup", json=body)
    r.raise_for_status()
    return r.json()


async def _set_consent(client: httpx.AsyncClient, token: str, scope: str, granted: bool) -> None:
    r = await client.post(
        f"{V1}/consents",
        headers=_bearer(token),
        json={"scope": scope, "granted": granted, "policy_text_version": "1.0"},
    )
    assert r.status_code == 201, f"consent set failed {r.status_code} {r.text}"


# ---------------------------------------------------------------------------
# Helpers to build resume files
# ---------------------------------------------------------------------------
def build_resume_docx() -> bytes:
    doc = DocxDocument()
    doc.add_heading("Aditi Rao", 0)
    doc.add_paragraph("aditi.rao.testuser@example.com | +1-555-0100 | Boston, MA")
    doc.add_paragraph("linkedin.com/in/aditi-rao-testuser")

    doc.add_heading("Education", 1)
    doc.add_paragraph("Massachusetts Institute of Technology — MS, Mechanical Engineering — 2024")
    doc.add_paragraph("Indian Institute of Technology Bombay — BTech, Mechanical Engineering — 2022")

    doc.add_heading("Experience", 1)
    doc.add_paragraph(
        "Rivian — Battery Systems Engineer (2024 - present). "
        "Owned pack-level thermal correlation and cell tab welding validation."
    )
    doc.add_paragraph(
        "Zoox — Battery Test Intern (Summer 2023). "
        "Ran DAQ instrumentation on cell test benches."
    )

    doc.add_heading("Projects", 1)
    doc.add_paragraph(
        "Cell-level busbar redesign — Achieved 18% reduction in joint resistance via FEA-driven busbar redesign."
    )

    doc.add_heading("Skills", 1)
    doc.add_paragraph("MATLAB, Simulink, Python, Ansys, GD&T, LabVIEW, DAQ instrumentation, Battery test benches")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_empty_docx() -> bytes:
    doc = DocxDocument()
    # No paragraphs at all
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_big_pdf(target_mb: int = 11) -> bytes:
    """Generate a PDF larger than the 10 MB upload limit."""
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf)
    # Each page has lots of text; enough pages to blow past target size.
    target_bytes = target_mb * 1024 * 1024
    page = 0
    while buf.tell() < target_bytes:
        page += 1
        y = 800
        # Also embed a big blob to bloat the file
        for i in range(60):
            c.drawString(20, y, ("filler " * 20) + f"page={page} line={i}")
            y -= 12
        c.showPage()
        if page > 400:
            break
    c.save()
    data = buf.getvalue()
    if len(data) < target_bytes:
        # pad with a comment stream so we cross the threshold
        pad = b"%pad " + (b"A" * (target_bytes - len(data) + 1024))
        data += pad
    return data


# ---------------------------------------------------------------------------
# 1. OpenAPI paths
# ---------------------------------------------------------------------------
async def check_openapi(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{API}/openapi.json")
    ok_status = r.status_code == 200
    spec = r.json() if ok_status else {}
    paths = set(spec.get("paths", {}).keys())

    phase1 = [
        "/api/v1/auth/signup", "/api/v1/auth/login", "/api/v1/auth/me",
        "/api/v1/consents", "/api/v1/consents/scopes",
        "/api/v1/users/me", "/api/v1/users/me/claims", "/api/v1/users/me/change-password",
        "/api/v1/users/{user_id}",
        "/api/v1/admin/feature-flags", "/api/v1/admin/health",
        "/api/v1/passport/ping", "/api/v1/meta/policy",
    ]
    phase2 = [
        "/api/v1/documents/resume",
        "/api/v1/documents/me",
        "/api/v1/documents/{document_id}/parse-status",
        "/api/v1/claims",
        "/api/v1/claims/{claim_id}/approve",
        "/api/v1/claims/{claim_id}/reject",
        "/api/v1/claims/{claim_id}",
        "/api/v1/claims/bulk-approve",
        "/api/v1/preferences",
        "/api/v1/preferences/me",
        "/api/v1/taxonomy",
        "/api/v1/companies",
        "/api/v1/eligibility",
        "/api/v1/eligibility/me",
        "/api/v1/eligibility/coverage-preview",
        "/api/v1/passport/activate",
        "/api/v1/passport/activation-status",
    ]
    missing_1 = [p for p in phase1 if p not in paths]
    missing_2 = [p for p in phase2 if p not in paths]
    _record(
        "1. openapi exposes all Phase-1 + Phase-2 paths",
        ok_status and not missing_1 and not missing_2,
        f"status={r.status_code} missing_phase1={missing_1} missing_phase2={missing_2}",
    )


# ---------------------------------------------------------------------------
# 2. Sample-job eligibility fixture integrity (direct Mongo probe)
# ---------------------------------------------------------------------------
async def check_sample_job_fixtures(db) -> None:
    total = await db.jobs.count_documents({"is_sample": True})
    _record("2a. exactly 15 is_sample:true jobs", total == 15, f"count={total}")

    us_person_jobs = [
        j async for j in db.jobs.find(
            {"is_sample": True, "eligibility_requirements.requires_us_person": True},
            {"title": 1, "_id": 0},
        )
    ]
    titles = sorted(j["title"] for j in us_person_jobs)
    expected_us = sorted(["Autonomy Systems Engineer", "Fab Equipment Engineer"])
    _record(
        "2b. 2 sample jobs requires_us_person=true (Autonomy + Fab Equipment)",
        titles == expected_us,
        f"titles={titles} expected={expected_us}",
    )

    no_spons = [
        j async for j in db.jobs.find(
            {"is_sample": True, "eligibility_requirements.offers_sponsorship": False},
            {"title": 1, "_id": 0},
        )
    ]
    ns_titles = sorted(j["title"] for j in no_spons)
    expected_ns = sorted([
        "Battery Test Engineer", "Battery Thermal Engineer",
        "Vehicle Test Engineer", "Manufacturing Process Engineer",
    ])
    _record(
        "2c. ≥4 sample jobs offers_sponsorship=false (four expected titles present)",
        set(expected_ns).issubset(set(ns_titles)) and len(ns_titles) >= 4,
        f"got={ns_titles} expected⊆={expected_ns}",
    )


# ---------------------------------------------------------------------------
# 3. Document upload contract
# ---------------------------------------------------------------------------
async def check_document_upload_contract(client: httpx.AsyncClient) -> tuple[str, str]:
    """Return (email, token) for the fresh QA user for reuse downstream."""
    email = f"qa2-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    pw = "TestPass!123"
    signup = await _signup(client, email=email, password=pw, name="QA Phase2 Uploader",
                           process_career=True)
    token = signup["access_token"]
    hdr = _bearer(token)

    # b. text/plain unsupported
    r = await client.post(
        f"{V1}/documents/resume",
        headers=hdr,
        files={"file": ("resume.txt", b"hello world", "text/plain")},
    )
    ok = r.status_code == 400 and r.json().get("detail", {}).get("error") == "unsupported_type"
    _record("3b. text/plain upload → 400 unsupported_type", ok,
            f"status={r.status_code} body={r.text[:200]}")

    # c. >10 MB PDF
    big_pdf = build_big_pdf(target_mb=11)
    r = await client.post(
        f"{V1}/documents/resume",
        headers=hdr,
        files={"file": ("big.pdf", big_pdf, "application/pdf")},
    )
    ok = r.status_code == 413 and r.json().get("detail", {}).get("error") == "file_too_large"
    _record(
        "3c. >10 MB PDF → 413 file_too_large",
        ok,
        f"status={r.status_code} size_mb={len(big_pdf)/1048576:.2f} body={r.text[:180]}",
    )

    # d. empty DOCX → 400 empty_file OR eventually failed parse
    empty = build_empty_docx()
    r = await client.post(
        f"{V1}/documents/resume",
        headers=hdr,
        files={
            "file": (
                "empty.docx",
                empty,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    detail_err = r.json().get("detail", {}).get("error") if r.status_code == 400 else None
    ok_400 = r.status_code == 400 and detail_err == "empty_file"
    ok_upload = r.status_code == 201
    empty_doc_id: str | None = None
    if ok_upload:
        empty_doc_id = r.json()["document"]["id"]

    if ok_400:
        _record("3d. empty DOCX → 400 empty_file", True, f"status=400 detail={detail_err}")
    elif ok_upload and empty_doc_id:
        # poll for extracted_text_too_short failure
        final_status = "unknown"
        err = None
        for _ in range(15):
            await asyncio.sleep(1.0)
            r2 = await client.get(f"{V1}/documents/{empty_doc_id}/parse-status", headers=hdr)
            if r2.status_code == 200:
                final_status = r2.json().get("parse_status")
                err = r2.json().get("parse_error")
                if final_status in ("failed", "completed"):
                    break
        _record(
            "3d. empty DOCX → parse failed with extracted_text_too_short",
            final_status == "failed" and (err == "extracted_text_too_short"),
            f"final_status={final_status} err={err}",
        )
    else:
        _record("3d. empty DOCX handling", False,
                f"status={r.status_code} body={r.text[:200]}")

    # e. Revoke process_career_data → 403 consent_required scope; regrant → 201
    await _set_consent(client, token, "process_career_data", False)
    docx_bytes = build_resume_docx()
    r = await client.post(
        f"{V1}/documents/resume",
        headers=hdr,
        files={"file": ("resume.docx", docx_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    ok_403 = (
        r.status_code == 403
        and r.json().get("detail", {}).get("error") == "consent_required"
        and r.json().get("detail", {}).get("scope") == "process_career_data"
    )
    _record("3e1. Upload w/o process_career_data → 403 consent_required", ok_403,
            f"status={r.status_code} body={r.text[:200]}")

    await _set_consent(client, token, "process_career_data", True)
    r = await client.post(
        f"{V1}/documents/resume",
        headers=hdr,
        files={"file": ("resume.docx", docx_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    _record("3e2. After re-grant, upload → 201", r.status_code == 201,
            f"status={r.status_code} body={r.text[:200]}")

    return email, token


# ---------------------------------------------------------------------------
# 4. Real LLM parse smoke test  (uses same fresh QA user)
# ---------------------------------------------------------------------------
async def check_llm_parse(client: httpx.AsyncClient, token: str, db) -> tuple[str, str, list[dict]]:
    """Returns (document_id, model_used, claims) so downstream checks can use it."""
    hdr = _bearer(token)

    # Deduplicate: use a novel resume so we get a fresh document / parse pipeline
    doc = DocxDocument()
    doc.add_heading("Nina Patel", 0)
    doc.add_paragraph("nina.patel.testuser@example.com | +1-555-0111 | San Jose, CA")
    doc.add_paragraph("linkedin.com/in/nina-patel-testuser")

    doc.add_heading("Education", 1)
    doc.add_paragraph("Stanford University — MS, Mechanical Engineering — 2023")
    doc.add_paragraph("BITS Pilani — BE, Mechanical Engineering — 2021")

    doc.add_heading("Experience", 1)
    doc.add_paragraph(
        "Lucid Motors — HV Systems Engineer (2023 - present). "
        "Owned busbar architecture and pack-level HV distribution."
    )
    doc.add_paragraph(
        "Tesla — Battery Cell Test Intern (Summer 2022). "
        "Ran capacity fade characterization on cylindrical cells."
    )

    doc.add_heading("Projects", 1)
    doc.add_paragraph(
        "Pack-level busbar redesign — Reduced joint resistance by 22% via CFD-driven busbar redesign."
    )

    doc.add_heading("Skills", 1)
    doc.add_paragraph("MATLAB, Simulink, Python, Ansys Fluent, GD&T, LabVIEW")

    buf = io.BytesIO()
    doc.save(buf)
    body = buf.getvalue()

    r = await client.post(
        f"{V1}/documents/resume",
        headers=hdr,
        files={"file": ("nina_resume.docx", body,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    if r.status_code != 201:
        _record("4a. resume upload → 201", False, f"status={r.status_code} body={r.text[:200]}")
        return "", "", []
    document_id = r.json()["document"]["id"]
    _record("4a. resume upload → 201", True, f"doc_id={document_id}")

    # Poll parse-status
    model_used = None
    inserted = None
    final = None
    async def _poll_once():
        nonlocal model_used, inserted, final
        rr = await client.get(f"{V1}/documents/{document_id}/parse-status", headers=hdr)
        if rr.status_code == 200:
            js = rr.json()
            final = js.get("parse_status")
            meta = js.get("parse_meta", {}) or {}
            model_used = meta.get("model_used")
            inserted = meta.get("inserted_claim_count")
        return final

    for attempt in (0, 1):
        deadline = time.time() + 120
        while time.time() < deadline:
            await _poll_once()
            if final in ("completed", "failed"):
                break
            await asyncio.sleep(2.0)
        if final == "completed":
            break
        if attempt == 0 and final == "failed":
            # retry once
            r = await client.post(
                f"{V1}/documents/resume",
                headers=hdr,
                files={"file": (f"nina_resume_{uuid.uuid4().hex[:6]}.docx", body,
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
            if r.status_code == 201:
                document_id = r.json()["document"]["id"]
                final = None
                continue
        break

    _record(
        "4b1. parse_status → completed within 120s (retry once allowed)",
        final == "completed",
        f"final={final} model={model_used} inserted={inserted}",
    )
    _record(
        "4b2. parse_meta.model_used is 'gpt-5' or 'gpt-4o'",
        model_used in ("gpt-5", "gpt-4o"),
        f"model_used={model_used}",
    )
    _record(
        "4b3. parse_meta.inserted_claim_count > 5",
        isinstance(inserted, int) and inserted > 5,
        f"inserted={inserted}",
    )

    # GET /api/v1/claims — every claim from this document must have expected shape
    r = await client.get(f"{V1}/claims", headers=hdr)
    groups = r.json().get("groups", []) if r.status_code == 200 else []
    from_doc: list[dict] = []
    # We need the raw source.document_id — read from DB directly, since the API serializer keeps source
    doc_claims_db = [
        c async for c in db.claims.find(
            {"user_id": (await db.users.find_one({"email": (await _me_email(client, token))})).get("id"),
             "source.document_id": document_id}, {"_id": 0})
    ]
    all_ok = True
    fail_details = []
    for c in doc_claims_db:
        chk = (
            c.get("source", {}).get("kind") == "resume_parse"
            and c.get("source", {}).get("model") == model_used
            and c.get("user_approved") is False
            and c.get("status") == "pending"
            and (c.get("verification") or {}).get("level") == 0
        )
        if not chk:
            all_ok = False
            fail_details.append({
                "id": c.get("id"), "src": c.get("source"),
                "approved": c.get("user_approved"), "status": c.get("status"),
                "vl": (c.get("verification") or {}).get("level"),
            })
    _record(
        "4c. Every parsed claim has source.kind=resume_parse, source.model matches, pending/unapproved/level0",
        all_ok and len(doc_claims_db) > 0,
        f"n_claims={len(doc_claims_db)} bad={fail_details[:3]}",
    )
    return document_id, (model_used or ""), doc_claims_db


async def _me_email(client: httpx.AsyncClient, token: str) -> str:
    r = await client.get(f"{V1}/auth/me", headers=_bearer(token))
    return r.json().get("email", "")


# ---------------------------------------------------------------------------
# 5. Claim lifecycle
# ---------------------------------------------------------------------------
async def check_claim_lifecycle(client: httpx.AsyncClient, token: str, db, doc_claims: list[dict]) -> None:
    hdr = _bearer(token)
    user = (await client.get(f"{V1}/auth/me", headers=hdr)).json()
    user_id = user["id"]

    if not doc_claims:
        _record("5. claim lifecycle", False, "no parsed claims available")
        return

    # Gather categories from doc claims
    skills = [c for c in doc_claims if c["type"] == "skill" and c.get("status") == "pending"]
    non_skill_pending = [c for c in doc_claims if c["type"] != "skill" and c.get("status") == "pending"]

    # 5a. Approve single with Idempotency-Key replay
    if not non_skill_pending:
        _record("5a. approve claim with idempotency replay", False, "no non-skill pending claim available")
    else:
        target = non_skill_pending[0]
        cid = target["id"]
        idem_key = f"qa-approve-{uuid.uuid4().hex}"
        r1 = await client.post(
            f"{V1}/claims/{cid}/approve",
            headers={**hdr, "Idempotency-Key": idem_key},
        )
        audit_before = await db.audit_logs.count_documents(
            {"actor": user_id, "action": "claim.approve", "object_ref": f"claim:{cid}"}
        )
        r2 = await client.post(
            f"{V1}/claims/{cid}/approve",
            headers={**hdr, "Idempotency-Key": idem_key},
        )
        audit_after = await db.audit_logs.count_documents(
            {"actor": user_id, "action": "claim.approve", "object_ref": f"claim:{cid}"}
        )
        byte_identical = r1.content == r2.content
        replay_hdr = r2.headers.get("X-Idempotent-Replay") == "true"
        c1 = r1.json()
        approved = c1.get("status") == "approved" and c1.get("user_approved") is True
        no_new_audit = (audit_after - audit_before) == 0
        _record(
            "5a. approve single + Idempotency replay (byte-identical, X-Idempotent-Replay:true, no dup audit)",
            r1.status_code == 200 and r2.status_code == 200 and approved and byte_identical and replay_hdr and no_new_audit,
            f"s1={r1.status_code} s2={r2.status_code} approved={approved} bytes_eq={byte_identical} replay={replay_hdr} audit_delta={audit_after - audit_before}",
        )

    # 5b. Reject a claim
    if len(non_skill_pending) < 2:
        _record("5b. reject a claim", False, "not enough pending non-skill claims")
    else:
        target = non_skill_pending[1]
        cid = target["id"]
        r = await client.post(f"{V1}/claims/{cid}/reject", headers=hdr)
        c = r.json() if r.status_code == 200 else {}
        ok = r.status_code == 200 and c.get("status") == "rejected" and c.get("user_approved") is False
        _record("5b. reject → status=rejected, user_approved=false", ok,
                f"status={r.status_code} c.status={c.get('status')} approved={c.get('user_approved')}")

    # 5c. Edit a claim → new version; old row value unchanged; superseded_by updated
    if len(non_skill_pending) < 3:
        _record("5c. edit claim", False, "not enough claims")
    else:
        target = non_skill_pending[2]
        cid = target["id"]
        old_value_before = target["value"]
        new_value = dict(old_value_before) if isinstance(old_value_before, dict) else {}
        new_value["_edited_marker"] = f"edit-{uuid.uuid4().hex[:8]}"

        r = await client.put(f"{V1}/claims/{cid}", headers=hdr, json={"value": new_value})
        new_c = r.json() if r.status_code == 200 else {}
        # Check DB state
        new_id = new_c.get("id")
        db_new = await db.claims.find_one({"id": new_id}) if new_id else None
        db_old = await db.claims.find_one({"id": cid})

        checks = {
            "status": r.status_code == 200,
            "new_c_version_2": new_c.get("version") == 2,
            "new_c_source_user_edited": (new_c.get("source") or {}).get("kind") == "user_edited",
            "new_c_from_claim_id": (new_c.get("source") or {}).get("from_claim_id") == cid,
            "new_c_from_version_1": (new_c.get("source") or {}).get("from_version") == 1,
            "new_c_superseded_by_null": new_c.get("superseded_by") in (None,),
            "db_old_superseded_by_new": db_old and db_old.get("superseded_by") == new_id,
            "db_old_value_unchanged": db_old and db_old.get("value") == old_value_before,
        }
        _record(
            "5c. edit → v2 with user_edited link, old row superseded_by=new_id, old value untouched",
            all(checks.values()),
            f"checks={checks}",
        )

    # 5d. Bulk approve type="skill"
    idem_key_b = f"qa-bulk-{uuid.uuid4().hex}"
    audit_before = await db.audit_logs.count_documents(
        {"actor": user_id, "action": "claims.bulk_approve"}
    )
    r = await client.post(
        f"{V1}/claims/bulk-approve",
        headers={**hdr, "Idempotency-Key": idem_key_b},
        json={"type": "skill"},
    )
    audit_after = await db.audit_logs.count_documents(
        {"actor": user_id, "action": "claims.bulk_approve"}
    )
    n_approved = r.json().get("approved_count", 0) if r.status_code == 200 else -1
    # Verify remaining pending skills = 0
    pending_skills = await db.claims.count_documents(
        {"user_id": user_id, "type": "skill", "status": "pending", "superseded_by": None}
    )
    _record(
        "5d. bulk-approve type=skill approves all pending skills + single audit row",
        r.status_code == 200 and n_approved >= len(skills) and pending_skills == 0 and (audit_after - audit_before) == 1,
        f"status={r.status_code} approved_count={n_approved} pending_skills_left={pending_skills} audit_delta={audit_after - audit_before}",
    )

    # 5e. Manual create — certification type
    r = await client.post(
        f"{V1}/claims",
        headers=hdr,
        json={
            "type": "certification",
            "value": {"name": "AWS Certified Solutions Architect", "issuer": "AWS", "year": 2024},
            "sensitivity": "normal",
        },
    )
    c = r.json() if r.status_code == 201 else {}
    ok = (
        r.status_code == 201
        and c.get("status") == "approved"
        and c.get("user_approved") is True
        and (c.get("source") or {}).get("kind") == "user_provided"
        and c.get("version") == 1
    )
    _record(
        "5e. Manual claim create → approved, user_provided, v1",
        ok,
        f"status={r.status_code} c.status={c.get('status')} src.kind={(c.get('source') or {}).get('kind')} version={c.get('version')}",
    )


# ---------------------------------------------------------------------------
# 6. Passport activation gate — use a FRESH user
# ---------------------------------------------------------------------------
async def check_passport_activation(client: httpx.AsyncClient, db) -> None:
    email = f"qa-activate-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    pw = "TestPass!123"
    signup = await _signup(client, email=email, password=pw, name="QA Activation")
    token = signup["access_token"]
    hdr = _bearer(token)
    me = (await client.get(f"{V1}/auth/me", headers=hdr)).json()
    user_id = me["id"]

    # a. Before any identity + edu/emp — activation should fail
    r = await client.post(f"{V1}/passport/activate", headers=hdr)
    detail = r.json().get("detail") if r.status_code == 400 else None
    ok = (
        r.status_code == 400
        and isinstance(detail, dict)
        and detail.get("error") == "activation_requirements_not_met"
        and set(detail.get("missing_categories", [])) == {"identity", "education_or_employment"}
    )
    _record(
        "6a. activate before approvals → 400 activation_requirements_not_met + missing_categories",
        ok,
        f"status={r.status_code} detail={detail}",
    )

    # b. Create one identity + one employment (manual create returns approved immediately)
    r_id = await client.post(f"{V1}/claims", headers=hdr, json={
        "type": "identity", "value": {"name": "QA Activation"}, "sensitivity": "normal",
    })
    r_emp = await client.post(f"{V1}/claims", headers=hdr, json={
        "type": "employment", "value": {"company": "ACME", "role": "Engineer"}, "sensitivity": "normal",
    })
    _record("6b1. manual identity + employment created", r_id.status_code == 201 and r_emp.status_code == 201,
            f"identity={r_id.status_code} employment={r_emp.status_code}")

    r = await client.get(f"{V1}/passport/activation-status", headers=hdr)
    js = r.json() if r.status_code == 200 else {}
    _record(
        "6b2. activation-status can_activate=true after identity + employment approved",
        r.status_code == 200 and js.get("can_activate") is True,
        f"status={r.status_code} js={js}",
    )

    # c. Activate — 200 {activated:true}
    idem_key = f"qa-activate-{uuid.uuid4().hex}"
    r1 = await client.post(f"{V1}/passport/activate",
                           headers={**hdr, "Idempotency-Key": idem_key})
    ok_activate = r1.status_code == 200 and r1.json().get("activated") is True
    # DB check
    u = await db.users.find_one({"id": user_id}, {"passport_activated": 1})
    audit = await db.audit_logs.find_one({"actor": user_id, "action": "passport.activate"})
    _record(
        "6c. activate → 200 activated:true, users.passport_activated=true, audit row present",
        ok_activate and (u or {}).get("passport_activated") is True and bool(audit),
        f"status={r1.status_code} body={r1.text[:150]} db_activated={(u or {}).get('passport_activated')} audit={bool(audit)}",
    )

    # d. Idempotency replay
    r2 = await client.post(f"{V1}/passport/activate",
                           headers={**hdr, "Idempotency-Key": idem_key})
    ok_replay = r2.status_code == 200 and r1.content == r2.content and r2.headers.get("X-Idempotent-Replay") == "true"
    _record("6d. activate idempotency replay = byte-identical + X-Idempotent-Replay:true",
            ok_replay,
            f"s1={r1.status_code} s2={r2.status_code} bytes_eq={r1.content == r2.content} replay_hdr={r2.headers.get('X-Idempotent-Replay')}")


# ---------------------------------------------------------------------------
# 7. Preferences
# ---------------------------------------------------------------------------
async def check_preferences(client: httpx.AsyncClient, db) -> None:
    email = f"qa-prefs-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    pw = "TestPass!123"
    signup = await _signup(client, email=email, password=pw, name="QA Prefs")
    token = signup["access_token"]
    hdr = _bearer(token)
    me = (await client.get(f"{V1}/auth/me", headers=hdr)).json()
    user_id = me["id"]

    payload = {
        "role_families": ["battery systems/test", "vehicle systems"],
        "locations": ["Phoenix, AZ", "San Jose, CA"],
        "remote_ok": True,
        "salary_floor_usd": 130000,
        "search_intensity": "medium",
        "employer_include": ["Lucid Motors"],
        "employer_exclude": ["SampleCo (demo)"],
        "notes": "Prefer battery / EV roles.",
    }
    k1 = f"qa-prefs-{uuid.uuid4().hex}"
    r1 = await client.post(f"{V1}/preferences", headers={**hdr, "Idempotency-Key": k1}, json=payload)
    v1 = r1.json().get("version") if r1.status_code == 201 else None
    _record("7a. save prefs (v1)", r1.status_code == 201 and v1 == 1, f"status={r1.status_code} version={v1}")

    # b. Same key replay
    r2 = await client.post(f"{V1}/preferences", headers={**hdr, "Idempotency-Key": k1}, json=payload)
    rows = await db.preferences.count_documents({"user_id": user_id})
    ok = (
        r2.status_code == 201
        and r1.content == r2.content
        and r2.headers.get("X-Idempotent-Replay") == "true"
        and rows == 1
    )
    _record("7b. Same Idempotency-Key → replay (no new row, X-Idempotent-Replay:true)",
            ok,
            f"s2={r2.status_code} bytes_eq={r1.content == r2.content} replay={r2.headers.get('X-Idempotent-Replay')} rows={rows}")

    # c. Different key, same payload → v2
    k2 = f"qa-prefs-{uuid.uuid4().hex}"
    r3 = await client.post(f"{V1}/preferences", headers={**hdr, "Idempotency-Key": k2}, json=payload)
    v3 = r3.json().get("version") if r3.status_code == 201 else None
    rows2 = await db.preferences.count_documents({"user_id": user_id})
    _record("7c. Different key + same payload → v2, rows=2", r3.status_code == 201 and v3 == 2 and rows2 == 2,
            f"status={r3.status_code} version={v3} rows={rows2}")

    # d. GET /me → v2
    r = await client.get(f"{V1}/preferences/me", headers=hdr)
    js = r.json() if r.status_code == 200 else {}
    _record("7d. GET /preferences/me → v2",
            r.status_code == 200 and js.get("version") == 2,
            f"status={r.status_code} version={js.get('version')}")

    # e. Taxonomy — 13 families
    r = await client.get(f"{V1}/taxonomy", headers=hdr)
    fams = r.json().get("families", []) if r.status_code == 200 else []
    _record("7e. /taxonomy returns 13 families",
            r.status_code == 200 and len(fams) == 13,
            f"status={r.status_code} count={len(fams)}")

    # f1. companies q=tsmc → TSMC only
    r = await client.get(f"{V1}/companies?q=tsmc", headers=hdr)
    cos = r.json().get("companies", []) if r.status_code == 200 else []
    names = [c.get("name") for c in cos]
    _record("7f1. /companies?q=tsmc returns only TSMC Arizona",
            r.status_code == 200 and names == ["TSMC Arizona"],
            f"names={names}")

    # f2. companies q= empty → sorted with SampleCo last
    r = await client.get(f"{V1}/companies?q=", headers=hdr)
    cos = r.json().get("companies", []) if r.status_code == 200 else []
    domains = [c.get("domain") for c in cos]
    sampleco_last = bool(domains) and domains[-1] == "sampleco.demo" and domains.count("sampleco.demo") == 1
    _record("7f2. /companies?q= empty returns list with SampleCo last",
            r.status_code == 200 and sampleco_last,
            f"n={len(domains)} last={domains[-1] if domains else None}")


# ---------------------------------------------------------------------------
# 8. Eligibility (owner-only)
# ---------------------------------------------------------------------------
async def check_eligibility(client: httpx.AsyncClient, db) -> tuple[str, str]:
    """Return (token, user_id) for reuse in coverage-preview checks."""
    email = f"qa-elig-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    pw = "TestPass!123"
    signup = await _signup(client, email=email, password=pw, name="QA Eligibility")
    token = signup["access_token"]
    hdr = _bearer(token)
    me = (await client.get(f"{V1}/auth/me", headers=hdr)).json()
    user_id = me["id"]

    # a. ead_opt
    r = await client.post(
        f"{V1}/eligibility",
        headers=hdr,
        json={"status": "ead_opt", "dates": {"opt_end": "2027-05-31"}},
    )
    js = r.json() if r.status_code == 201 else {}
    df = js.get("derived_flags") or {}
    ok = (
        r.status_code == 201
        and js.get("sealed") is True
        and js.get("version") == 1
        and df.get("itar_excluded") is True
        and df.get("e_verify_need") is True
        and df.get("sponsorship_need") is True
    )
    _record(
        "8a. eligibility ead_opt → derived flags correct, sealed:true, v1",
        ok,
        f"status={r.status_code} version={js.get('version')} sealed={js.get('sealed')} df={df}",
    )

    # b. /eligibility/me returns same
    r = await client.get(f"{V1}/eligibility/me", headers=hdr)
    js2 = r.json() if r.status_code == 200 else {}
    _record(
        "8b. /eligibility/me returns same profile",
        r.status_code == 200 and js2.get("status") == "ead_opt" and js2.get("version") == 1,
        f"status={r.status_code} me={js2}",
    )

    # c. citizen
    r = await client.post(f"{V1}/eligibility", headers=hdr, json={"status": "citizen", "dates": {}})
    js3 = r.json() if r.status_code == 201 else {}
    df3 = js3.get("derived_flags") or {}
    ok3 = (
        r.status_code == 201
        and js3.get("version") == 2
        and df3.get("itar_excluded") is False
        and df3.get("e_verify_need") is False
        and df3.get("sponsorship_need") is False
    )
    _record(
        "8c. eligibility citizen → all derived flags false, v2",
        ok3,
        f"status={r.status_code} v={js3.get('version')} df={df3}",
    )

    # d. latest wins in DB
    latest = await db.eligibility_profiles.find_one({"user_id": user_id}, sort=[("version", -1)])
    rows = await db.eligibility_profiles.count_documents({"user_id": user_id})
    _record(
        "8d. second version stored, latest.status=citizen",
        latest and latest.get("status") == "citizen" and latest.get("version") == 2 and rows == 2,
        f"latest_status={(latest or {}).get('status')} latest_v={(latest or {}).get('version')} rows={rows}",
    )

    return token, user_id


# ---------------------------------------------------------------------------
# 9. Coverage preview
# ---------------------------------------------------------------------------
async def check_coverage_preview(client: httpx.AsyncClient) -> None:
    # a. new user, no discover_jobs consent
    email = f"qa-cov-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    pw = "TestPass!123"
    signup = await _signup(client, email=email, password=pw, name="QA Coverage", process_career=True)
    token = signup["access_token"]
    hdr = _bearer(token)

    r = await client.get(f"{V1}/eligibility/coverage-preview", headers=hdr)
    ok = (
        r.status_code == 403
        and r.json().get("detail", {}).get("error") == "consent_required"
        and r.json().get("detail", {}).get("scope") == "discover_jobs"
    )
    _record("9a. Without discover_jobs consent → 403 consent_required scope=discover_jobs",
            ok, f"status={r.status_code} body={r.text[:200]}")

    # b. Grant discover_jobs, save eligibility ead_opt, check totals
    await _set_consent(client, token, "discover_jobs", True)
    r = await client.post(f"{V1}/eligibility", headers=hdr,
                          json={"status": "ead_opt", "dates": {"opt_end": "2027-05-31"}})
    assert r.status_code == 201, f"eligibility save failed {r.status_code} {r.text}"

    r = await client.get(f"{V1}/eligibility/coverage-preview", headers=hdr)
    js = r.json() if r.status_code == 200 else {}
    totals = js.get("totals") or {}
    ex = totals.get("excluded_by_reason") or {}
    ok_b = (
        r.status_code == 200
        and totals.get("live_jobs") == 15
        and ex.get("requires_us_person") == 2
        and ex.get("no_sponsorship_offered") == 4
        and totals.get("passing") == 9
    )
    _record(
        "9b. ead_opt → live=15, requires_us_person=2, no_sponsorship_offered=4, passing=9",
        ok_b,
        f"status={r.status_code} totals={totals}",
    )

    # d. Every job in list carries fail_reasons array
    jobs = js.get("jobs") or []
    ok_shape = all(isinstance(j.get("fail_reasons"), list) for j in jobs)
    passing_have_empty = all(len(j.get("fail_reasons") or []) == 0 for j in jobs if j.get("pass_all"))
    _record("9d. Every job carries fail_reasons array; passing jobs have empty array",
            ok_shape and passing_have_empty and len(jobs) == 15,
            f"n_jobs={len(jobs)} shape_ok={ok_shape} passing_empty={passing_have_empty}")

    # c. Change eligibility to citizen → passing == 15
    r = await client.post(f"{V1}/eligibility", headers=hdr,
                          json={"status": "citizen", "dates": {}})
    assert r.status_code == 201, f"eligibility save citizen failed {r.status_code} {r.text}"

    r = await client.get(f"{V1}/eligibility/coverage-preview", headers=hdr)
    js2 = r.json() if r.status_code == 200 else {}
    totals2 = js2.get("totals") or {}
    ex2 = totals2.get("excluded_by_reason") or {}
    ok_c = totals2.get("live_jobs") == 15 and totals2.get("passing") == 15
    _record("9c. citizen → passing=15, excluded may be empty",
            ok_c, f"totals={totals2}")


# ---------------------------------------------------------------------------
# 10. Sealed serializer (regression)
# ---------------------------------------------------------------------------
async def check_sealed_serializer(client: httpx.AsyncClient) -> None:
    uz_login = await _login(client, *USER_ZERO)
    admin_login = await _login(client, *ADMIN)
    support_login = await _login(client, *SUPPORT)
    uz_token = uz_login["access_token"]
    uz_id = uz_login["user"]["id"]

    # a. Owner sees real value
    r = await client.get(f"{V1}/users/me/claims", headers=_bearer(uz_token))
    if r.status_code == 200:
        # Endpoint groups claims by type — flatten
        groups = r.json().get("groups") or r.json().get("claims")
        if isinstance(groups, list) and groups and isinstance(groups[0], dict) and "claims" in groups[0]:
            all_claims = [c for g in groups for c in g.get("claims", [])]
        else:
            all_claims = groups if isinstance(groups, list) else []
    else:
        all_claims = []
    wa = next((c for c in all_claims if c.get("type") == "work_auth"), None)
    ok = (wa is not None
          and wa.get("sensitivity") == "sealed"
          and isinstance(wa.get("value"), dict)
          and wa["value"].get("status") == "unspecified"
          and "_sealed" not in wa)
    _record("10a. Owner sees real work_auth value, no _sealed flag", ok,
            f"wa={wa if wa else 'missing'}")

    # b. Admin sees masked
    r = await client.get(f"{V1}/users/{uz_id}", headers=_bearer(admin_login["access_token"]))
    claims = r.json().get("claims", []) if r.status_code == 200 else []
    wa = next((c for c in claims if c.get("type") == "work_auth"), None)
    ok = (wa is not None and wa.get("value") == "•••• (sealed)" and wa.get("_sealed") is True)
    _record("10b. Admin sees masked work_auth", ok,
            f"wa_value={wa.get('value') if wa else '-'} _sealed={wa.get('_sealed') if wa else '-'}")

    # c. Support sees masked
    r = await client.get(f"{V1}/users/{uz_id}", headers=_bearer(support_login["access_token"]))
    claims = r.json().get("claims", []) if r.status_code == 200 else []
    wa = next((c for c in claims if c.get("type") == "work_auth"), None)
    ok = (wa is not None and wa.get("value") == "•••• (sealed)" and wa.get("_sealed") is True)
    _record("10c. Support sees masked work_auth", ok,
            f"wa_value={wa.get('value') if wa else '-'} _sealed={wa.get('_sealed') if wa else '-'}")


# ---------------------------------------------------------------------------
# 11. Consent gates on new endpoints
# ---------------------------------------------------------------------------
async def check_consent_gates_new(client: httpx.AsyncClient) -> None:
    email = f"qa-gates-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    pw = "TestPass!123"
    signup = await _signup(client, email=email, password=pw, name="QA Gates",
                           process_career=True, discover_jobs=False)
    token = signup["access_token"]
    hdr = _bearer(token)

    # Revoke process_career_data
    await _set_consent(client, token, "process_career_data", False)

    # documents/resume — require process_career_data
    docx = build_resume_docx()
    r = await client.post(
        f"{V1}/documents/resume", headers=hdr,
        files={"file": ("r.docx", docx,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    ok = r.status_code == 403 and r.json().get("detail", {}).get("scope") == "process_career_data"
    _record("11a. documents/resume without process_career_data → 403",
            ok, f"status={r.status_code} body={r.text[:200]}")

    # claims/* — require process_career_data
    r = await client.get(f"{V1}/claims", headers=hdr)
    ok = r.status_code == 403 and r.json().get("detail", {}).get("scope") == "process_career_data"
    _record("11b. GET /claims without process_career_data → 403",
            ok, f"status={r.status_code} body={r.text[:200]}")

    # preferences POST — require process_career_data
    r = await client.post(f"{V1}/preferences", headers=hdr, json={
        "role_families": ["vehicle systems"], "locations": ["Phoenix, AZ"],
    })
    ok = r.status_code == 403 and r.json().get("detail", {}).get("scope") == "process_career_data"
    _record("11c. POST /preferences without process_career_data → 403",
            ok, f"status={r.status_code} body={r.text[:200]}")

    # eligibility POST — require process_career_data
    r = await client.post(f"{V1}/eligibility", headers=hdr,
                          json={"status": "citizen", "dates": {}})
    ok = r.status_code == 403 and r.json().get("detail", {}).get("scope") == "process_career_data"
    _record("11d. POST /eligibility without process_career_data → 403",
            ok, f"status={r.status_code} body={r.text[:200]}")

    # coverage-preview — require discover_jobs (also require career? router uses require_consent("discover_jobs") only)
    r = await client.get(f"{V1}/eligibility/coverage-preview", headers=hdr)
    ok = r.status_code == 403 and r.json().get("detail", {}).get("scope") == "discover_jobs"
    _record("11e. GET /eligibility/coverage-preview without discover_jobs → 403",
            ok, f"status={r.status_code} body={r.text[:200]}")

    # Re-grant process_career_data and prove flows work again
    await _set_consent(client, token, "process_career_data", True)
    r = await client.get(f"{V1}/claims", headers=hdr)
    _record("11f. After re-grant process_career_data → GET /claims 200",
            r.status_code == 200, f"status={r.status_code}")

    await _set_consent(client, token, "discover_jobs", True)
    # eligibility must exist for coverage-preview to be meaningful, but should still respond 200
    r = await client.get(f"{V1}/eligibility/coverage-preview", headers=hdr)
    _record("11g. After granting discover_jobs → coverage-preview 200",
            r.status_code == 200, f"status={r.status_code}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    mongo = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = mongo[DB_NAME]

    uz = await db.users.find_one({"email": "ujjwal@opportunityos.dev"})
    if not uz:
        print("FATAL: User Zero missing"); return 1

    async with httpx.AsyncClient(timeout=180.0) as client:
        # (1) openapi
        await check_openapi(client)

        # (2) sample-job fixtures (mongo probe)
        await check_sample_job_fixtures(db)

        # (3) document upload contract + (4) LLM parse
        _email_qa, token_qa = await check_document_upload_contract(client)
        document_id, model_used, doc_claims = await check_llm_parse(client, token_qa, db)

        # (5) claim lifecycle
        await check_claim_lifecycle(client, token_qa, db, doc_claims)

        # (6) passport activation (fresh user)
        await check_passport_activation(client, db)

        # (7) preferences (fresh user)
        await check_preferences(client, db)

        # (8) eligibility (fresh user)
        await check_eligibility(client, db)

        # (9) coverage preview (fresh user)
        await check_coverage_preview(client)

        # (10) sealed serializer regression on User Zero
        await check_sealed_serializer(client)

        # (11) consent gates on new endpoints
        await check_consent_gates_new(client)

    print("\n\n===== SUMMARY =====")
    fails = [r for r in RESULTS if not r[1]]
    passes = [r for r in RESULTS if r[1]]
    print(f"Total: {len(RESULTS)} — PASS: {len(passes)} — FAIL: {len(fails)}")
    if fails:
        print("\nFailures:")
        for name, _, ev in fails:
            print(f"  - {name}\n      {ev}")
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

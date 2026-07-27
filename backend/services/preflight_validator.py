"""Pre-flight validator — Phase 5.0 dispatch chokepoint (Founder Directive 2026-07-28).

RULE:
  Before ANY outbound submission (email route now; real form/API later),
  machine-diff every outbound field and every resume line against the
  approved Passport claim it traces to. Untraceable line or mismatch →
  BLOCK and route to `review` lane with reason `validator_blocked_mismatch`.
  Validator verdict stored ON the receipt. Zero unvalidated submissions
  by construction — enforced at the dispatch chokepoint so no code path
  can bypass it.

This module composes the existing line-level firewall
(`services/validator.py::validate_lines`, which enforces claim
traceability + number/year grounding + sealed-value leak scanning) and
adds pre-flight checks specific to the dispatch surface:

  * Identity coherence — Passport identity claim's `name` / `email` /
    `phone` must match the outbound `subject` / `body` / `destination`
    where those fields appear.
  * Outbound-text grounding — numbers and 4-digit years in the outbound
    `subject` and `body` must appear in at least one approved claim.
  * Sealed-value leak in outbound text — sealed claims (work_auth,
    salary, clearance) may NEVER surface in outbound text unless the
    caller supplies a per-application sealed approval.
  * Approved-claims-not-empty — a user with zero approved claims cannot
    submit at all (there is nothing to trace to).
  * Materials integrity — if the caller supplies `expected_manifest_hash`,
    the current resume-version manifest hash must equal it.

Enforcement is at three places today; adding a new dispatch route MUST
call `preflight_check` before writing an outbox row, a submission
receipt, or otherwise causing outbound behaviour.

Callers today:
  * `domains/submit_sprint/__init__.py::confirm_slot`  (channel=sprint_fixture)
  * `domains/email_route/__init__.py::dispatch`        (channel=email_dry_run)
  * (future) `domains/applications/service.py::submit` (channel=form_live)
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from core import db as core_db
from services import validator as line_validator


# Stable failure reasons — never rename without adjusting frontend copy
# in `frontend/src/pages/Feed.jsx` and the review-lane UI.
REASON_TOP_LEVEL = "validator_blocked_mismatch"
REASON_NO_APPROVED_CLAIMS = "no_approved_claims"
REASON_NO_MATERIALS = "no_materials"
REASON_MANIFEST_MISMATCH = "manifest_mismatch"
REASON_LINE_VALIDATION_FAILED = "line_validation_failed"
REASON_IDENTITY_MISMATCH = "identity_mismatch"
REASON_NUMBER_NOT_IN_CLAIMS = "number_not_in_claims"
REASON_DATE_NOT_IN_CLAIMS = "date_not_in_claims"
REASON_SENSITIVE_LEAK = "sensitive_leak"


# Channels — every dispatch path must declare which channel it's on.
CHANNEL_SPRINT_FIXTURE = "sprint_fixture"
CHANNEL_EMAIL_DRY_RUN = "email_dry_run"
CHANNEL_EMAIL_LIVE = "email_live"
CHANNEL_FORM_LIVE = "form_live"
_ALL_CHANNELS = {
    CHANNEL_SPRINT_FIXTURE, CHANNEL_EMAIL_DRY_RUN,
    CHANNEL_EMAIL_LIVE, CHANNEL_FORM_LIVE,
}


@dataclass
class PreflightVerdict:
    """Structured verdict — always emitted, even on pass."""
    id: str
    ok: bool
    channel: str
    user_id: str
    application_id: str
    reasons: list[str] = field(default_factory=list)
    line_stats: dict = field(default_factory=dict)
    field_findings: list[dict] = field(default_factory=list)
    identity_check: dict = field(default_factory=dict)
    materials_source: str | None = None
    checked_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ok": self.ok,
            "channel": self.channel,
            "user_id": self.user_id,
            "application_id": self.application_id,
            "reasons": list(self.reasons),
            "line_stats": dict(self.line_stats),
            "field_findings": list(self.field_findings),
            "identity_check": dict(self.identity_check),
            "materials_source": self.materials_source,
            "checked_at": self.checked_at,
        }

    def compact(self) -> dict:
        """Trimmed shape suitable for embedding in a submission receipt."""
        return {
            "id": self.id,
            "ok": self.ok,
            "channel": self.channel,
            "reasons": list(self.reasons),
            "line_stats": dict(self.line_stats),
            "identity_ok": self.identity_check.get("ok", None),
            "checked_at": self.checked_at,
        }


async def _load_approved_claims(user_id: str) -> list[dict]:
    db = core_db.get_db()
    cur = db.claims.find({"user_id": user_id, "status": "approved"},
                         {"_id": 0})
    return [c async for c in cur]


async def _load_manifest_lines(application_id: str, user_id: str) -> tuple[list[dict], str | None]:
    """Return (manifest lines, resume_version_id). Falls back to base resume
    manifest if the application has no tailored resume attached yet — that
    still validates against approved claims, which is what we care about.
    """
    db = core_db.get_db()
    app_row = await db.applications.find_one(
        {"id": application_id, "user_id": user_id},
        {"_id": 0, "materials": 1},
    ) or {}
    version_id = ((app_row.get("materials") or {})
                  .get("resume_version_id"))
    if version_id:
        rv = await db.resume_versions.find_one({"id": version_id}, {"_id": 0})
        if rv:
            lines = ((rv.get("render_manifest") or {}).get("lines") or [])
            return lines, version_id
    base = await db.resume_versions.find_one(
        {"user_id": user_id, "base": True}, {"_id": 0})
    if base:
        return ((base.get("render_manifest") or {}).get("lines") or []), base.get("id")
    return [], None


def _canonical_identity(approved_claims: list[dict]) -> dict:
    """Extract normalized Passport identity facts from approved claims."""
    ident = {"name": None, "email": None, "phone": None}
    for c in approved_claims:
        if c.get("type") == "identity":
            v = c.get("value") or {}
            if isinstance(v, dict):
                for k in ("name", "email", "phone"):
                    if v.get(k) and not ident[k]:
                        ident[k] = str(v[k]).strip()
        elif c.get("type") == "contact":
            v = c.get("value") or {}
            if isinstance(v, dict):
                for k in ("email", "phone"):
                    if v.get(k) and not ident[k]:
                        ident[k] = str(v[k]).strip()
    return ident


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")


def _identity_check(outbound_fields: dict | None, ident: dict) -> dict:
    """For email-channel dispatches, confirm the outbound `destination` /
    `subject` / `body` don't impersonate a *different* identity than the
    Passport's approved identity. We look for two failure modes:

      1. An email address in the outbound body/subject that isn't the
         employer's destination and isn't the Passport identity's own
         email → suspicious impersonation, block.
      2. A `from`-style name in the outbound subject/body that contradicts
         the Passport name → block.

    Returns `{ok: bool, findings: [{reason, field, value}, ...]}`.
    """
    result = {"ok": True, "findings": []}
    if not outbound_fields:
        return result

    destination = (outbound_fields.get("destination") or "").lower().strip()
    subject = outbound_fields.get("subject") or ""
    body = outbound_fields.get("body") or ""
    passport_email = (ident.get("email") or "").lower().strip()
    passport_name = ident.get("name") or ""

    # (1) Any additional email in subject/body that isn't the employer or
    # the Passport identity is a leak/impersonation risk.
    for field_name, text in (("subject", subject), ("body", body)):
        for m in _EMAIL_RE.finditer(text):
            email = m.group(0).lower()
            if email == destination or email == passport_email:
                continue
            result["ok"] = False
            result["findings"].append({
                "reason": REASON_IDENTITY_MISMATCH,
                "field": field_name,
                "value": email,
                "detail": (f"Email address in {field_name!s} is neither the "
                           f"employer destination nor the Passport identity."),
            })

    # (2) Impersonation via name — extremely conservative match. We only
    # trigger this if the outbound text contains a well-formed "Sincerely,
    # <name>" / "Best, <name>" / "-- <name>" signature that doesn't match
    # the Passport identity name.
    if passport_name:
        for sig_re in (r"Sincerely,\s*([A-Z][a-zA-Z .'-]{1,60})",
                        r"Best(?:\s+regards)?,\s*([A-Z][a-zA-Z .'-]{1,60})",
                        r"--\s*([A-Z][a-zA-Z .'-]{1,60})"):
            for m in re.finditer(sig_re, body):
                sig_name = m.group(1).strip()
                if sig_name.lower() != passport_name.lower():
                    result["ok"] = False
                    result["findings"].append({
                        "reason": REASON_IDENTITY_MISMATCH,
                        "field": "body_signature",
                        "value": sig_name,
                        "detail": (f"Body signature {sig_name!r} does not "
                                   f"match Passport identity {passport_name!r}."),
                    })
    return result


def _outbound_text_check(outbound_fields: dict | None,
                          approved_claims: list[dict],
                          sealed_approvals: Iterable[str]) -> list[dict]:
    """Apply the SAME number/year grounding + sealed-leak scan the
    line-validator does — but to the outbound `subject` and `body`.

    Every 2+ digit number and every 4-digit year in the outbound text
    must appear in at least one approved claim. Sealed values must
    never appear unless the caller supplied a per-app sealed approval.
    """
    findings: list[dict] = []
    if not outbound_fields:
        return findings

    subject = outbound_fields.get("subject") or ""
    body = outbound_fields.get("body") or ""

    # Union of numbers and years across all approved claims.
    allowed_numbers: set[str] = set()
    allowed_years: set[str] = set()
    for c in approved_claims:
        allowed_numbers |= line_validator._numbers_in_claim(c)
        allowed_years |= line_validator._years_in_claim(c)
    sealed_approvals = set(sealed_approvals or [])

    for field_name, text in (("subject", subject), ("body", body)):
        # numbers
        for n in line_validator._extract_numbers(text):
            normalized = n.rstrip("kKM%")
            try:
                if len(normalized) < 2 and float(normalized) < 10:
                    continue
            except ValueError:
                continue
            if n not in allowed_numbers:
                findings.append({
                    "reason": f"{REASON_NUMBER_NOT_IN_CLAIMS}:{n}",
                    "field": field_name,
                    "value": n,
                })
        # years
        for y in line_validator._extract_years(text):
            if y not in allowed_years:
                findings.append({
                    "reason": f"{REASON_DATE_NOT_IN_CLAIMS}:{y}",
                    "field": field_name,
                    "value": y,
                })
        # sealed leaks
        text_lower = text.lower()
        for c in approved_claims:
            if (c.get("sensitivity") or "").lower() != "sealed":
                continue
            ctype = c.get("type") or ""
            if ctype in sealed_approvals:
                continue
            for token in line_validator._sensitive_leak_tokens(c):
                if token.lower() in text_lower:
                    findings.append({
                        "reason": f"{REASON_SENSITIVE_LEAK}:{ctype}",
                        "field": field_name,
                        "value": token,
                    })
                    break
    return findings


def _manifest_hash(lines: list[dict]) -> str:
    """Deterministic hash of the manifest lines. Order matters; we hash
    a canonical JSON encoding of the (text, claim_ids) tuples."""
    canonical = json.dumps(
        [(L.get("text"), sorted(L.get("claim_ids") or [])) for L in lines],
        sort_keys=True, ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _finalize_blocked(verdict: "PreflightVerdict") -> "PreflightVerdict":
    """Ensure the top-level `validator_blocked_mismatch` code is the FIRST
    reason on every blocked verdict, so downstream code can switch on a
    single stable identifier."""
    if not verdict.ok and REASON_TOP_LEVEL not in verdict.reasons:
        verdict.reasons.insert(0, REASON_TOP_LEVEL)
    return verdict


async def preflight_check(
    *,
    user_id: str,
    application_id: str,
    channel: str,
    outbound_fields: dict | None = None,
    expected_manifest_hash: str | None = None,
    per_application_sealed_approvals: Iterable[str] = (),
) -> PreflightVerdict:
    """Dispatch-chokepoint validation. Never raises for a rule failure —
    returns a `PreflightVerdict` with `ok=False` and a `reasons` list.
    Callers MUST inspect `verdict.ok` and refuse to write outbound state
    when it is False.
    """
    if channel not in _ALL_CHANNELS:
        # Programmer error — this IS an unrecoverable failure of the
        # dispatch chokepoint. Raise, don't return a "block" verdict,
        # because a caller passing an unknown channel would otherwise
        # get an unexplained block.
        raise ValueError(f"unknown dispatch channel: {channel!r}")

    now_iso = datetime.now(timezone.utc).isoformat()
    verdict = PreflightVerdict(
        id=str(uuid.uuid4()),
        ok=True,
        channel=channel,
        user_id=user_id,
        application_id=application_id,
        checked_at=now_iso,
    )

    # 1. Approved claims must exist.
    approved = await _load_approved_claims(user_id)
    if not approved:
        verdict.ok = False
        verdict.reasons.append(REASON_NO_APPROVED_CLAIMS)
        return _finalize_blocked(verdict)

    # 2. Materials manifest must exist and validate line-by-line.
    manifest_lines, source = await _load_manifest_lines(application_id, user_id)
    verdict.materials_source = source
    if not manifest_lines:
        verdict.ok = False
        verdict.reasons.append(REASON_NO_MATERIALS)
        return _finalize_blocked(verdict)

    # 3. Optional integrity check — caller can pass a stored hash and we
    # confirm the manifest hasn't been mutated out from under them.
    if expected_manifest_hash:
        actual = _manifest_hash(manifest_lines)
        if actual != expected_manifest_hash:
            verdict.ok = False
            verdict.reasons.append(REASON_MANIFEST_MISMATCH)
            verdict.line_stats["expected_hash"] = expected_manifest_hash
            verdict.line_stats["actual_hash"] = actual
            return _finalize_blocked(verdict)

    # 4. Line-level validation — every line must reference approved claims,
    # every number/year must be in the referenced claims, no sensitive leak.
    line_res = line_validator.validate_lines(
        lines=manifest_lines, approved_claims=approved,
        per_application_sealed_approvals=per_application_sealed_approvals,
    )
    verdict.line_stats = {
        "total": line_res.stats["total"],
        "passed": line_res.stats["passed"],
        "rejected": line_res.stats["rejected"],
        # Only surface the FIRST 5 rejection details to keep verdict
        # size reasonable — the full detail is always in the ValidatorResult.
        "sample_rejections": line_res.rejected_lines[:5],
    }
    if line_res.status == "failed":
        verdict.ok = False
        verdict.reasons.append(
            f"{REASON_LINE_VALIDATION_FAILED}:{line_res.stats['rejected']}")

    # 5. Outbound-field grounding (only when outbound_fields provided).
    if outbound_fields:
        field_findings = _outbound_text_check(
            outbound_fields, approved,
            sealed_approvals=per_application_sealed_approvals,
        )
        # 6. Identity coherence.
        ident = _canonical_identity(approved)
        id_check = _identity_check(outbound_fields, ident)
        verdict.identity_check = {"ok": id_check["ok"],
                                    "findings": id_check["findings"]}
        verdict.field_findings = field_findings + id_check["findings"]
        if field_findings or not id_check["ok"]:
            verdict.ok = False
            for f in field_findings:
                if f["reason"] not in verdict.reasons:
                    verdict.reasons.append(f["reason"])
            if not id_check["ok"] and REASON_IDENTITY_MISMATCH not in verdict.reasons:
                verdict.reasons.append(REASON_IDENTITY_MISMATCH)

    if not verdict.ok:
        # Prepend the top-level block code so downstream code can
        # switch on a single stable identifier.
        return _finalize_blocked(verdict)
    return verdict


async def persist_verdict(verdict: PreflightVerdict) -> None:
    """Persist to `preflight_verdicts` for auditability."""
    db = core_db.get_db()
    doc = verdict.to_dict()
    doc["_persisted_at"] = datetime.now(timezone.utc)
    await db.preflight_verdicts.insert_one(doc)


async def block_and_route_to_review(
    verdict: PreflightVerdict,
    audit_actor: str | None = None,
) -> None:
    """On a blocked verdict: (a) persist the verdict, (b) move the
    application into `review` state with reason `validator_blocked_mismatch`,
    and (c) audit-log the block. Callers still return HTTP 422 to the
    client — this helper only handles the durable side-effects."""
    if verdict.ok:
        return  # nothing to do
    await persist_verdict(verdict)
    db = core_db.get_db()
    await db.applications.update_one(
        {"id": verdict.application_id, "user_id": verdict.user_id},
        {"$set": {
            "state": "review",
            "review_reason": REASON_TOP_LEVEL,
            "review_verdict_id": verdict.id,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    # Audit-log so the review-lane UI can explain "why we didn't send".
    try:
        from domains.audit import service as audit
        await audit.write(
            audit_actor or verdict.user_id, "preflight.blocked",
            f"application:{verdict.application_id}",
            {"channel": verdict.channel, "reasons": verdict.reasons,
             "verdict_id": verdict.id},
        )
    except Exception:
        # Never let audit failure escalate — the block must stand
        # regardless of audit persistence success.
        pass

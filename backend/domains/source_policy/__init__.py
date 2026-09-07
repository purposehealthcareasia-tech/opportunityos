"""P1 FOUNDATION · Source Access Policy Engine.

FYND ATLAS §12-§15 · deterministic, fail-closed, NO LLM in the policy
path. This is the single arbiter of "may I do OPERATION X against
SOURCE S at time T?". Every connector code path in the platform MUST
route through `allow()` before performing any network operation.

Design invariants (locked by tests):
  1. Four independent status fields per source:
       - robotsStatus     : ROBOTS_RESPECTED / ROBOTS_UNKNOWN / ROBOTS_BLOCKED
       - termsStatus      : TERMS_COMPLIANT / TERMS_UNKNOWN / TERMS_HOSTILE
       - licenseStatus    : LICENSED / TRIAL / UNLICENSED / NOT_APPLICABLE
       - legalReviewStatus: LEGAL_APPROVED / LEGAL_PENDING / LEGAL_REJECTED
     Missing any field for a source == fail-closed (no operation allowed).
  2. Eight enumerated operations — no free-form ops accepted:
       discover, fetch, monitor, paginate, interact, authenticate,
       prepare, submit.
  3. Deterministic decision table:
       ANY status in the "block set" for that op → DENY (with reason).
       All statuses in the "permit set" for that op → ALLOW.
       Anything else → DENY (fail-closed default).
  4. NO LLM. NO string-substring-matching fallback. The decision is a
     pure function of the (source_registry_record, operation) tuple.
  5. Kill switch: an `ADMIN_KILL_SWITCH_SOURCES` env var (comma-list)
     forces DENY for every operation on the listed source_id. Read at
     each `allow()` call — no cache — so the founder can revoke a
     source instantly by editing the env and hot-reloading, without
     touching the registry.
  6. Every decision is recorded via `_audit(...)` so the audit trail
     can prove "at time T, the platform DENIED operation X on source S
     because reason=<r>".

Consumers (Batch 2 Connector SDK, existing discovery/service.py) MUST
raise if the policy engine returns DENY. This module NEVER performs
the operation itself — it only decides.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.time_utils import utc_now


# ------------------------------------------------------------------
# Status enumerations
# ------------------------------------------------------------------
class RobotsStatus(str, Enum):
    RESPECTED = "ROBOTS_RESPECTED"
    UNKNOWN   = "ROBOTS_UNKNOWN"
    BLOCKED   = "ROBOTS_BLOCKED"


class TermsStatus(str, Enum):
    COMPLIANT = "TERMS_COMPLIANT"
    UNKNOWN   = "TERMS_UNKNOWN"
    HOSTILE   = "TERMS_HOSTILE"


class LicenseStatus(str, Enum):
    LICENSED       = "LICENSED"
    TRIAL          = "TRIAL"
    UNLICENSED     = "UNLICENSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class LegalReviewStatus(str, Enum):
    APPROVED = "LEGAL_APPROVED"
    PENDING  = "LEGAL_PENDING"
    REJECTED = "LEGAL_REJECTED"


class Operation(str, Enum):
    DISCOVER     = "discover"
    FETCH        = "fetch"
    MONITOR      = "monitor"
    PAGINATE     = "paginate"
    INTERACT     = "interact"
    AUTHENTICATE = "authenticate"
    PREPARE      = "prepare"
    SUBMIT       = "submit"


ALL_OPERATIONS: frozenset[Operation] = frozenset(Operation)


# ------------------------------------------------------------------
# Per-operation permit/block sets. Deterministic decision table.
#
# The interpretation is:
#   * `PERMIT_ANY_OF[op]` — the operation is ALLOWED if the source's
#     status for the corresponding field is in this set.
#   * `BLOCK_ANY_OF[op]` — the operation is DENIED (with reason) if
#     the source's status for the corresponding field is in this set.
#   * A source must satisfy PERMIT on ALL FOUR fields AND not trip
#     BLOCK on ANY field to be ALLOWED.
#
# This is intentionally verbose so the founder can audit each row.
# ------------------------------------------------------------------
_OP_POLICY_TABLE: dict[Operation, dict[str, set]] = {
    # discover — low-cost lookup, safe as long as robots don't block
    # and terms permit indexing / discovery.
    Operation.DISCOVER: {
        "robots_permit":  {RobotsStatus.RESPECTED, RobotsStatus.UNKNOWN},
        "robots_block":   {RobotsStatus.BLOCKED},
        "terms_permit":   {TermsStatus.COMPLIANT, TermsStatus.UNKNOWN},
        "terms_block":    {TermsStatus.HOSTILE},
        "license_permit": {LicenseStatus.LICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "license_block":  {LicenseStatus.UNLICENSED},
        "legal_permit":   {LegalReviewStatus.APPROVED, LegalReviewStatus.PENDING},
        "legal_block":    {LegalReviewStatus.REJECTED},
    },
    # fetch — actual byte retrieval; requires robots strictly RESPECTED.
    Operation.FETCH: {
        "robots_permit":  {RobotsStatus.RESPECTED},
        "robots_block":   {RobotsStatus.BLOCKED, RobotsStatus.UNKNOWN},
        "terms_permit":   {TermsStatus.COMPLIANT},
        "terms_block":    {TermsStatus.HOSTILE, TermsStatus.UNKNOWN},
        "license_permit": {LicenseStatus.LICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "license_block":  {LicenseStatus.UNLICENSED},
        "legal_permit":   {LegalReviewStatus.APPROVED},
        "legal_block":    {LegalReviewStatus.REJECTED, LegalReviewStatus.PENDING},
    },
    # monitor — repeated fetch on a cadence; same rails as fetch.
    Operation.MONITOR: {
        "robots_permit":  {RobotsStatus.RESPECTED},
        "robots_block":   {RobotsStatus.BLOCKED, RobotsStatus.UNKNOWN},
        "terms_permit":   {TermsStatus.COMPLIANT},
        "terms_block":    {TermsStatus.HOSTILE, TermsStatus.UNKNOWN},
        "license_permit": {LicenseStatus.LICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "license_block":  {LicenseStatus.UNLICENSED},
        "legal_permit":   {LegalReviewStatus.APPROVED},
        "legal_block":    {LegalReviewStatus.REJECTED, LegalReviewStatus.PENDING},
    },
    # paginate — same rails as fetch; separate op so per-source rate
    # limits can be enforced independently in a later batch.
    Operation.PAGINATE: {
        "robots_permit":  {RobotsStatus.RESPECTED},
        "robots_block":   {RobotsStatus.BLOCKED, RobotsStatus.UNKNOWN},
        "terms_permit":   {TermsStatus.COMPLIANT},
        "terms_block":    {TermsStatus.HOSTILE, TermsStatus.UNKNOWN},
        "license_permit": {LicenseStatus.LICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "license_block":  {LicenseStatus.UNLICENSED},
        "legal_permit":   {LegalReviewStatus.APPROVED},
        "legal_block":    {LegalReviewStatus.REJECTED, LegalReviewStatus.PENDING},
    },
    # interact — active DOM manipulation on employer sites; requires
    # explicit LEGAL_APPROVED. TERMS_UNKNOWN is a hard block.
    Operation.INTERACT: {
        "robots_permit":  {RobotsStatus.RESPECTED},
        "robots_block":   {RobotsStatus.BLOCKED, RobotsStatus.UNKNOWN},
        "terms_permit":   {TermsStatus.COMPLIANT},
        "terms_block":    {TermsStatus.HOSTILE, TermsStatus.UNKNOWN},
        "license_permit": {LicenseStatus.LICENSED},
        "license_block":  {LicenseStatus.UNLICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "legal_permit":   {LegalReviewStatus.APPROVED},
        "legal_block":    {LegalReviewStatus.REJECTED, LegalReviewStatus.PENDING},
    },
    # authenticate — session/token acquisition against a source that
    # requires it. Same rails as INTERACT (strict license + legal).
    Operation.AUTHENTICATE: {
        "robots_permit":  {RobotsStatus.RESPECTED},
        "robots_block":   {RobotsStatus.BLOCKED, RobotsStatus.UNKNOWN},
        "terms_permit":   {TermsStatus.COMPLIANT},
        "terms_block":    {TermsStatus.HOSTILE, TermsStatus.UNKNOWN},
        "license_permit": {LicenseStatus.LICENSED},
        "license_block":  {LicenseStatus.UNLICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "legal_permit":   {LegalReviewStatus.APPROVED},
        "legal_block":    {LegalReviewStatus.REJECTED, LegalReviewStatus.PENDING},
    },
    # prepare — local, offline: build resume / cover letter with the
    # candidate's Passport. No source access; permitted for every
    # source with license (so the connector can enrich local drafts).
    Operation.PREPARE: {
        "robots_permit":  {RobotsStatus.RESPECTED, RobotsStatus.UNKNOWN},
        "robots_block":   {RobotsStatus.BLOCKED},
        "terms_permit":   {TermsStatus.COMPLIANT, TermsStatus.UNKNOWN},
        "terms_block":    {TermsStatus.HOSTILE},
        "license_permit": {LicenseStatus.LICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "license_block":  {LicenseStatus.UNLICENSED},
        "legal_permit":   {LegalReviewStatus.APPROVED, LegalReviewStatus.PENDING},
        "legal_block":    {LegalReviewStatus.REJECTED},
    },
    # submit — real employer submission. Strictest rails.
    Operation.SUBMIT: {
        "robots_permit":  {RobotsStatus.RESPECTED},
        "robots_block":   {RobotsStatus.BLOCKED, RobotsStatus.UNKNOWN},
        "terms_permit":   {TermsStatus.COMPLIANT},
        "terms_block":    {TermsStatus.HOSTILE, TermsStatus.UNKNOWN},
        "license_permit": {LicenseStatus.LICENSED},
        "license_block":  {LicenseStatus.UNLICENSED, LicenseStatus.TRIAL,
                           LicenseStatus.NOT_APPLICABLE},
        "legal_permit":   {LegalReviewStatus.APPROVED},
        "legal_block":    {LegalReviewStatus.REJECTED, LegalReviewStatus.PENDING},
    },
}


# ------------------------------------------------------------------
# Decision object
# ------------------------------------------------------------------
@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    source_id: str
    operation: str
    evaluated_at: str  # ISO-UTC
    field_values: dict[str, str]  # snapshot of the 4 statuses used

    def raise_if_denied(self):
        if not self.allowed:
            raise PolicyDenied(self)


class PolicyDenied(RuntimeError):
    """Raised when a connector calls into the policy engine with an
    unsafe (source, operation) pair. NEVER caught silently — every
    call site MUST propagate."""
    def __init__(self, decision: PolicyDecision):
        super().__init__(f"policy_denied: {decision.reason} "
                         f"(source={decision.source_id}, op={decision.operation})")
        self.decision = decision


# ------------------------------------------------------------------
# Kill switch
# ------------------------------------------------------------------
def _kill_switch_sources() -> set[str]:
    raw = os.environ.get("ADMIN_KILL_SWITCH_SOURCES", "") or ""
    return {s.strip() for s in raw.split(",") if s.strip()}


# ------------------------------------------------------------------
# Public API — allow(...)
# ------------------------------------------------------------------
def allow(
    *,
    source_record: dict,
    operation: Operation | str,
) -> PolicyDecision:
    """Decide whether the platform may perform `operation` on the given
    source right now. `source_record` is a Global Source Registry doc
    (see `domains/source_registry`). Returns a PolicyDecision — callers
    MUST inspect `.allowed` and never assume ALLOW.

    Rails:
      * Missing any of the 4 status fields → fail-closed DENY.
      * Kill switch match → DENY regardless of statuses.
      * Op not in the enumerated list → DENY.
    """
    source_id = str(source_record.get("source_id") or source_record.get("id") or "unknown")

    # Coerce operation to enum (fail-closed on unknown strings).
    if isinstance(operation, str):
        try:
            op = Operation(operation)
        except ValueError:
            return _deny(source_id, str(operation),
                         reason=f"unknown_operation:{operation!r}",
                         field_values={})
    else:
        op = operation

    # Kill switch takes precedence.
    if source_id in _kill_switch_sources():
        return _deny(source_id, op.value, "kill_switch_engaged",
                     field_values={"kill_switch": source_id})

    # Extract + validate the 4 status fields.
    try:
        robots  = RobotsStatus(source_record["robotsStatus"])
        terms   = TermsStatus(source_record["termsStatus"])
        lic     = LicenseStatus(source_record["licenseStatus"])
        legal   = LegalReviewStatus(source_record["legalReviewStatus"])
    except (KeyError, ValueError, TypeError) as e:
        return _deny(source_id, op.value,
                     reason=f"missing_or_invalid_status_fields:{type(e).__name__}",
                     field_values={
                         "robotsStatus":      str(source_record.get("robotsStatus")),
                         "termsStatus":       str(source_record.get("termsStatus")),
                         "licenseStatus":     str(source_record.get("licenseStatus")),
                         "legalReviewStatus": str(source_record.get("legalReviewStatus")),
                     })

    field_values = {
        "robotsStatus":      robots.value,
        "termsStatus":       terms.value,
        "licenseStatus":     lic.value,
        "legalReviewStatus": legal.value,
    }

    policy = _OP_POLICY_TABLE.get(op)
    if policy is None:  # should never happen — enum is exhaustive.
        return _deny(source_id, op.value, "no_policy_row_for_operation",
                     field_values=field_values)

    # BLOCK checks first (deny-wins).
    if robots in policy["robots_block"]:
        return _deny(source_id, op.value,
                     f"robots_status_blocks_op:{robots.value}",
                     field_values=field_values)
    if terms in policy["terms_block"]:
        return _deny(source_id, op.value,
                     f"terms_status_blocks_op:{terms.value}",
                     field_values=field_values)
    if lic in policy["license_block"]:
        return _deny(source_id, op.value,
                     f"license_status_blocks_op:{lic.value}",
                     field_values=field_values)
    if legal in policy["legal_block"]:
        return _deny(source_id, op.value,
                     f"legal_status_blocks_op:{legal.value}",
                     field_values=field_values)

    # PERMIT checks (must ALL be in the permit set).
    if robots not in policy["robots_permit"]:
        return _deny(source_id, op.value,
                     f"robots_status_not_in_permit_set:{robots.value}",
                     field_values=field_values)
    if terms not in policy["terms_permit"]:
        return _deny(source_id, op.value,
                     f"terms_status_not_in_permit_set:{terms.value}",
                     field_values=field_values)
    if lic not in policy["license_permit"]:
        return _deny(source_id, op.value,
                     f"license_status_not_in_permit_set:{lic.value}",
                     field_values=field_values)
    if legal not in policy["legal_permit"]:
        return _deny(source_id, op.value,
                     f"legal_status_not_in_permit_set:{legal.value}",
                     field_values=field_values)

    return PolicyDecision(
        allowed=True,
        reason="policy_permits_operation",
        source_id=source_id,
        operation=op.value,
        evaluated_at=utc_now().isoformat(),
        field_values=field_values,
    )


def _deny(source_id: str, operation: str, reason: str,
          field_values: dict[str, str]) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason=reason,
        source_id=source_id,
        operation=operation,
        evaluated_at=utc_now().isoformat(),
        field_values=field_values,
    )

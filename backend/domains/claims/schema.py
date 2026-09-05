"""Claims schema — SINGLE SOURCE OF TRUTH for field names + value keys.

Every module that touches `db.claims.*` MUST import these constants
instead of writing raw string literals. Doing otherwise creates the
same class of drift that hit Phase 5 Gate C · FIX 1 (interview_prep
used {"state","kind"} while the collection actually stores
{"status","type"} — every category returned the empty state and the
generation path was silently unreachable), and its second layer
FIX 1B (interview_prep + share both read c.get("data") while the
collection actually stores the value sub-document under `value`).

Anti-drift lock: `tests/test_claims_schema_no_drift_guard.py` scans
`domains/**/*.py` (excluding `domains/claims/`) for hardcoded
`"state"` / `"kind"` / `"data"` string keys near `db.claims.*` reads.
If any callsite bypasses this module, the guard fails at CI.
"""
from __future__ import annotations


# ------------------------------------------------------------------
# Collection top-level field names (as actually written by
# domains/claims/repository.py + the seeder in seeds/seeder.py).
# ------------------------------------------------------------------
FIELD_TYPE = "type"                # NOT "kind"
FIELD_STATUS = "status"            # NOT "state"
FIELD_USER_ID = "user_id"
FIELD_SUPERSEDED_BY = "superseded_by"
FIELD_VALUE = "value"              # NOT "data" (Gate C · FIX 1B)
FIELD_ID = "id"


# ------------------------------------------------------------------
# Enumerated status + type values.
# ------------------------------------------------------------------
STATUS_APPROVED = "approved"
STATUS_PENDING = "pending"
STATUS_REJECTED = "rejected"

TYPE_IDENTITY = "identity"
TYPE_EDUCATION = "education"
TYPE_EMPLOYMENT = "employment"
TYPE_SKILL = "skill"
TYPE_PROJECT = "project"

ALLOWED_TYPES = frozenset({TYPE_IDENTITY, TYPE_EDUCATION, TYPE_EMPLOYMENT, TYPE_SKILL, TYPE_PROJECT})


# ------------------------------------------------------------------
# Per-type value-block keys (as actually written by the seeder + the
# domains.claims.service writer — see FIXTURE_CLAIMS in seeds/data.py
# for the authoritative shape). Consumers that project a claim's
# `value` sub-doc MUST pull from these constants. Historical drift
# (Gate C · FIX 1B):
#   * interview_prep + share both read c.get("data") — no such field
#     exists at rest; they returned empty forever.
#   * interview_prep expected education["school"] / ["graduation_year"];
#     the collection stores education["institution"] + ["end"]
#     ("YYYY-MM") — see FIXTURE_CLAIMS.
#   * interview_prep expected employment["title"] / ["start_year"];
#     the collection stores employment["role"] + ["start"] ("YYYY-MM").
#
# Hotfix Gate (2026-08-13) — IDENTITY_VALUE_KEYS: the manual-claim
# modal now exposes structured identity fields matching what a candidate
# actually says on a resume: legal first + legal last (both required for
# signature-check math) + preferred_name (optional, what they'd like to
# be called in outbound emails). Legacy `{"name": "..."}` payload shape
# still accepted by `preflight_validator._canonical_identity` for
# backward compat with pre-Hotfix stored identity claims — the reader
# derives `name` from `preferred_name` OR `f"{legal_first} {legal_last}"`.
# ------------------------------------------------------------------
IDENTITY_VALUE_KEYS   = ("legal_first", "legal_last", "preferred_name")
EDUCATION_VALUE_KEYS  = ("institution", "degree", "field", "start", "end")
EMPLOYMENT_VALUE_KEYS = ("company", "role", "start", "end", "summary")
SKILL_VALUE_KEYS      = ("name",)
PROJECT_VALUE_KEYS    = ("name", "description")

VALUE_KEYS_BY_TYPE = {
    TYPE_IDENTITY:   IDENTITY_VALUE_KEYS,
    TYPE_EDUCATION:  EDUCATION_VALUE_KEYS,
    TYPE_EMPLOYMENT: EMPLOYMENT_VALUE_KEYS,
    TYPE_SKILL:      SKILL_VALUE_KEYS,
    TYPE_PROJECT:    PROJECT_VALUE_KEYS,
}


# ------------------------------------------------------------------
# Canonical accessors — consumers should PREFER these over
# raw-dict construction / bare .get() calls with hardcoded strings.
# ------------------------------------------------------------------
def approved_for_user_query(user_id: str) -> dict:
    """Standard filter for 'all approved, non-superseded claims for
    user'. This is the canonical read every grounded-generation path
    should use."""
    return {
        FIELD_USER_ID: user_id,
        FIELD_STATUS: STATUS_APPROVED,
        FIELD_SUPERSEDED_BY: None,
    }


def is_approved(claim: dict) -> bool:
    return claim.get(FIELD_STATUS) == STATUS_APPROVED


def claim_type(claim: dict) -> str:
    return claim.get(FIELD_TYPE) or ""


def claim_value(claim: dict) -> dict:
    """Return the claim's value sub-document. Handles both the
    canonical `value` key (production + seeder) and the legacy
    `data` key (some older unit-test fixtures). Prefers `value`.
    Never returns None so callers can .get() safely.
    """
    v = claim.get(FIELD_VALUE)
    if isinstance(v, dict):
        return v
    d = claim.get("data")
    if isinstance(d, dict):
        return d
    return {}


def _year_from_iso_month(iso_month: str | None) -> int | None:
    """Parse 'YYYY-MM' or 'YYYY-MM-DD' into a 4-digit int year; None
    on any parse failure. Never raises."""
    if not iso_month or not isinstance(iso_month, str):
        return None
    try:
        return int(iso_month[:4])
    except Exception:
        return None

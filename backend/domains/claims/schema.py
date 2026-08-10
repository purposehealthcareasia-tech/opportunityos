"""Claims schema — SINGLE SOURCE OF TRUTH for field names.

Every module that touches `db.claims.*` MUST import these constants
instead of writing raw string literals. Doing otherwise creates the
same class of drift that hit Phase 5 Gate C · FIX 1 (interview_prep
used {"state","kind"} while the collection actually stores
{"status","type"} — every category returned the empty state and the
generation path was silently unreachable).

Anti-drift lock: `tests/test_claims_schema_no_drift_guard.py` scans
`domains/**/*.py` (excluding `domains/claims/`) for hardcoded
`"state"` / `"kind"` string keys in `db.claims.find(...)` calls. If
any callsite bypasses this module, the guard fails at CI.
"""
from __future__ import annotations


# ------------------------------------------------------------------
# Collection field names (as actually written by domains/claims/repository.py).
# ------------------------------------------------------------------
FIELD_TYPE = "type"       # NOT "kind"
FIELD_STATUS = "status"   # NOT "state"
FIELD_USER_ID = "user_id"
FIELD_SUPERSEDED_BY = "superseded_by"
FIELD_DATA = "data"
FIELD_ID = "id"


# ------------------------------------------------------------------
# Enumerated values (guarded — any consumer that needs a state literal
# uses these constants).
# ------------------------------------------------------------------
STATUS_APPROVED = "approved"
STATUS_PENDING = "pending"
STATUS_REJECTED = "rejected"

TYPE_EDUCATION = "education"
TYPE_EMPLOYMENT = "employment"
TYPE_SKILL = "skill"
TYPE_PROJECT = "project"

ALLOWED_TYPES = frozenset({TYPE_EDUCATION, TYPE_EMPLOYMENT, TYPE_SKILL, TYPE_PROJECT})


# ------------------------------------------------------------------
# Canonical query helpers — consumers should PREFER these over
# raw-dict construction. Returning a dict makes them Motor-safe.
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

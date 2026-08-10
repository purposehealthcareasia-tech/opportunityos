"""Claims schema anti-drift guard.

Same class as `test_consent_scope_enum_guard.py`. Prevents the
"schema drift" bug that hit Phase 5 Gate C · FIX 1:

  * `domains/interview_prep/service.py` queried `db.claims` with
    `state="approved"` and filtered on `kind`, while the collection
    actually stores `status` + `type` (see
    `domains/claims/repository.py`). Every category silently
    returned the empty state → generation path unreachable.
  * Same bug lived in `domains/share/service.py::_load_filtered_passport`.
    Fixed in the same pass.

STRUCTURAL FIX: `domains/claims/schema.py` is the SINGLE SOURCE OF
TRUTH for claims field names + status values + type values +
canonical query builders. Any consumer touching `db.claims.*` MUST
import from `schema.py`. The guards below enforce that mechanically.
"""
from __future__ import annotations

import re
from pathlib import Path


BACKEND_DOMAINS = Path("/app/backend/domains")

# The two names that historically drifted. If a future contributor
# uses either literal against `db.claims`, the guard fails.
FORBIDDEN_LITERALS = ("state", "kind")

# Whitelist: modules that legitimately own or manipulate the claims
# collection's raw structure (schema.py + repository.py + the models
# that back the collection itself). Everything ELSE must use the
# accessors.
WHITELIST_PARTS = {"schema.py", "repository.py", "models.py"}


def _find_offenders() -> list[tuple[str, int, str]]:
    offenders: list[tuple[str, int, str]] = []
    for py in BACKEND_DOMAINS.rglob("*.py"):
        if py.name in WHITELIST_PARTS:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Focus on file regions that reference `db.claims`. We look at
        # a small window around every `db.claims` mention to catch
        # local raw-literal filters.
        for m in re.finditer(r"db\.claims\.", text):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 400)
            window = text[start:end]
            for lit in FORBIDDEN_LITERALS:
                pattern = rf'["\']{lit}["\']\s*:'
                if re.search(pattern, window):
                    line_no = text.count("\n", 0, m.start()) + 1
                    offenders.append((str(py), line_no, lit))
    return offenders


def test_no_raw_state_or_kind_literals_near_db_claims_reads():
    """Any callsite that reads/writes `db.claims` MUST use the
    accessors from `domains/claims/schema.py` (approved_for_user_query,
    is_approved, claim_type, FIELD_STATUS, FIELD_TYPE, ...). A raw
    `"state":` or `"kind":` literal near a `db.claims.*` call fails
    this guard immediately.

    Root cause it prevents (verbatim from Phase-5 Gate C · FIX 1):
      > queries `db.claims` with `state:"approved"` and filters on
      > `c.get("kind")`, but the collection actually stores
      > `status:"approved"` and `type`.
    """
    offenders = _find_offenders()
    assert not offenders, (
        "Raw claims field literals detected near `db.claims.*` calls.\n"
        "Use `domains/claims/schema.py` accessors instead. Offenders:\n"
        + "\n".join(f"  - {p}:{n}   forbidden literal: '{lit}'"
                     for p, n, lit in offenders)
    )


def test_schema_module_has_required_accessors():
    """The single source of truth must expose the minimal accessor
    surface every consumer needs. If a future refactor removes one of
    these, this test flags it immediately."""
    from domains.claims import schema
    for attr in (
        "FIELD_TYPE", "FIELD_STATUS", "FIELD_USER_ID", "FIELD_SUPERSEDED_BY",
        "STATUS_APPROVED", "STATUS_PENDING", "STATUS_REJECTED",
        "TYPE_EDUCATION", "TYPE_EMPLOYMENT", "TYPE_SKILL", "TYPE_PROJECT",
        "ALLOWED_TYPES",
        "approved_for_user_query", "is_approved", "claim_type",
    ):
        assert hasattr(schema, attr), (
            f"domains/claims/schema.py MUST expose `{attr}` — "
            "consumers depend on it as the single source of truth.")


def test_schema_field_names_match_the_repository():
    """Independent check: the schema's `FIELD_TYPE` / `FIELD_STATUS`
    must equal the literals used in `domains/claims/repository.py`
    (which is the authoritative writer). If the repository changes
    the field names, this test fails and forces schema.py to update
    at the same commit."""
    from domains.claims import schema
    repo_text = Path("/app/backend/domains/claims/repository.py").read_text()
    assert f'"{schema.FIELD_TYPE}"' in repo_text or f"'{schema.FIELD_TYPE}'" in repo_text
    assert f'"{schema.FIELD_STATUS}"' in repo_text or f"'{schema.FIELD_STATUS}'" in repo_text

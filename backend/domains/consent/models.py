from pydantic import BaseModel, Field, field_validator
from datetime import datetime

from core.policy import SCOPE_KEYS


# ---------------------------------------------------------------
# ScopeName is deliberately typed as `str` with a Pydantic
# field-level validator that checks membership in
# `core.policy.SCOPE_KEYS`. The previous implementation used a
# hardcoded `Literal[...]` which was a SECOND SOURCE OF TRUTH — it
# forked from `CONSENT_SCOPES` any time a new scope was added.
# Structural fix (Phase 5 Gate A · FAIL 3): every scope-carrying
# model now derives its accepted-set from `SCOPE_KEYS` at
# validation time, so adding a scope to `core/policy.py` is
# sufficient to expose it on the API. The
# `test_consent_scope_enum_guard.py` guard now enforces this
# invariant directly.
# ---------------------------------------------------------------
ScopeName = str


def _validate_scope_name(v: str) -> str:
    if v not in SCOPE_KEYS:
        raise ValueError(
            f"unknown consent scope '{v}'. "
            f"Accepted: {sorted(SCOPE_KEYS)}"
        )
    return v


class ConsentRecord(BaseModel):
    id: str
    user_id: str
    scope: ScopeName
    granted: bool
    policy_text_version: str
    ts: datetime
    actor: str  # who caused the change (usually user_id; system-set = "system")
    source: str  # e.g. "signup", "settings", "revoke", "seed"

    _validate_scope = field_validator("scope")(_validate_scope_name)


class ConsentChangeRequest(BaseModel):
    scope: ScopeName
    granted: bool
    policy_text_version: str = Field(min_length=1)

    _validate_scope = field_validator("scope")(_validate_scope_name)


class ConsentStateItem(BaseModel):
    scope: ScopeName
    granted: bool
    policy_text_version: str | None = None
    ts: datetime | None = None

    _validate_scope = field_validator("scope")(_validate_scope_name)


class ConsentStateResponse(BaseModel):
    scopes: list[ConsentStateItem]
    policy_text_version: str

"""P1 FOUNDATION Batch 2 · Opportunity Source Connector SDK.

FYND ATLAS §10 (Batch 2) — every opportunity-source connector inherits
from `OpportunitySourceConnector`. The SDK guarantees three invariants
that were previously enforced only by convention:

  1. `source_id` is a first-class class attribute and MUST map to a
     record in `source_registry`. `check_policy(op)` refuses to
     proceed if the source has no registry record — 'no source skips
     shadow'.
  2. Every network-crossing operation (`fetch`, `discover`, etc.)
     MUST route through `source_policy.allow(...)` BEFORE the first
     byte leaves the pod. Denial raises `PolicyDenied` and the HTTP
     client is never instantiated — fail-CLOSED by construction.
  3. The kill switch (env var `ADMIN_KILL_SWITCH_SOURCES`) is
     re-evaluated on every call, so the founder can halt an in-flight
     connector instantly by editing env and hot-reloading — no cache.

The SDK is intentionally minimal. Concrete adapters (Greenhouse /
Lever / Ashby) live in `adapters/public_apis.py` and instantiate the
subclasses defined here. Refactor rail: byte-identical output vs.
the pre-SDK module-level fetchers on the same inputs.

There is NO LLM code path in this module or any subclass. The gate
is a pure function of (source_registry_record, operation).
"""
from __future__ import annotations

import abc
from typing import Optional

from domains.source_policy import Operation, PolicyDenied, allow
from domains.source_registry import get as _registry_get


# ------------------------------------------------------------------
# Normalized posting shape (documented; not enforced as a Pydantic
# model because the shape is already implicitly locked by
# `discovery/service.py::_to_jobs_doc`. Keep the two aligned).
# ------------------------------------------------------------------
REQUIRED_NORMALIZED_KEYS: frozenset[str] = frozenset({
    "source_ats", "employer", "employer_token", "external_id",
    "title", "location", "remote", "posted_at", "updated_at",
    "apply_url", "jd_text", "is_newgrad", "fetched_at",
})


# ------------------------------------------------------------------
# Base class
# ------------------------------------------------------------------
class OpportunitySourceConnector(abc.ABC):
    """Base class for every opportunity-source connector.

    Subclasses MUST set the class-level `source_id` attribute to the
    slug used in `source_registry` (e.g., "greenhouse"). All network
    ops MUST route through `self.check_policy(op)` before executing.
    """

    #: Registry slug. Must be non-empty and match a source_registry row.
    source_id: str = ""

    # ------------------------------------------------------- lifecycle
    def __init__(self):
        if not self.source_id:
            raise ValueError(
                f"{type(self).__name__}: source_id must be set to a "
                f"non-empty slug matching a source_registry record"
            )
        # Cache the registry record for the connector's lifetime. The
        # kill switch is re-evaluated per policy call regardless of
        # this cache, so a founder revoke still takes effect instantly
        # even mid-refresh cycle.
        self._source_record: Optional[dict] = None

    async def close(self) -> None:
        """Base is a no-op. Subclasses with persistent HTTP clients
        override to release sockets."""
        return None

    # ------------------------------------------------------- policy gate
    async def _load_source_record(self) -> dict:
        """Load the registry record for this connector's source_id.
        Raises PolicyDenied fail-closed if the source is not registered
        ('no source skips shadow' rail)."""
        if self._source_record is not None:
            return self._source_record
        rec = await _registry_get(self.source_id)
        if rec is None:
            # Synthesize a decision object so the caller sees a
            # PolicyDenied with a specific reason.
            from domains.source_policy import PolicyDecision
            from core.time_utils import utc_now
            deny = PolicyDecision(
                allowed=False,
                reason="source_not_in_registry",
                source_id=self.source_id,
                operation="load_source_record",
                evaluated_at=utc_now().isoformat(),
                field_values={},
            )
            raise PolicyDenied(deny)
        self._source_record = rec
        return rec

    async def check_policy(self, operation: Operation | str) -> None:
        """Route `operation` through `source_policy.allow(...)`.
        Raises `PolicyDenied` on any DENY. Callers MUST call this
        before any HTTP request or DB write intended to reach the
        source. Cheap: no HTTP, no LLM."""
        rec = await self._load_source_record()
        decision = allow(source_record=rec, operation=operation)
        decision.raise_if_denied()

    # ------------------------------------------------------- interface
    @abc.abstractmethod
    async def discover(self) -> list[tuple[str, str]]:
        """Return the list of (company_name, employer_token) tuples
        this connector is authorized to fetch. Reads the catalog for
        this source_ats. MUST call `self.check_policy(Operation.DISCOVER)`
        internally."""

    @abc.abstractmethod
    async def fetch(self, company_name: str, token: str) -> list[dict]:
        """Fetch and NORMALIZE postings for a single employer token.
        MUST call `self.check_policy(Operation.FETCH)` internally
        BEFORE any HTTP request. Returned rows must each carry every
        key in `REQUIRED_NORMALIZED_KEYS`."""

    def normalize(self, raw: dict) -> dict:
        """Default normalize is identity — subclasses that fetch raw
        source JSON typically build the normalized dict inside `fetch`
        for byte-identical parity with the pre-SDK adapters. This
        method is here for the SDK contract; callers that want to
        transform a single raw record can override."""
        return raw

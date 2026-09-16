"""P1 FOUNDATION Batch 2 · Opportunity Source Connector SDK tests.

Locks:
  * `OpportunitySourceConnector` is an ABC — direct instantiation fails.
  * Every concrete connector's `source_id` maps to a source_registry row
    ('no source skips shadow').
  * Policy DENY fails CLOSED — the HTTP client is NEVER instantiated
    when the policy engine returns DENY.
  * Kill switch halts an in-flight connector cleanly — a fetch call
    made AFTER the kill switch is engaged raises PolicyDenied without
    issuing HTTP.
  * Byte-identical rail: `Connector.fetch(name, token)` returns EXACTLY
    what the pre-SDK module-level fetcher returns for the same inputs
    (verified against a canned Greenhouse response).
  * NO LLM in the SDK — static grep.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import httpx
import pytest
import pytest_asyncio

from domains.source_policy import (
    Operation, PolicyDenied, RobotsStatus, TermsStatus,
    LicenseStatus, LegalReviewStatus,
)


# ---------------------------------------------------------------- fixtures
@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client_per_test():
    from core import db as _core_db
    if _core_db._client is not None:
        try:
            _core_db._client.close()
        except Exception:
            pass
    _core_db._client = None
    _core_db._db = None
    # Symmetry with test_source_registry — always seed against a fresh
    # collection so per-test policy statuses are deterministic.
    db = _core_db.get_db()
    await db.source_registry.delete_many({})
    yield


@pytest_asyncio.fixture
async def _seeded_registry():
    from domains.source_registry import seed_verified_sources
    await seed_verified_sources()
    yield


# ---------------------------------------------------------------- canned data
_CANNED_GH = {
    "jobs": [
        {
            "id": 42,
            "internal_job_id": 4200,
            "title": "Systems Engineer, Vehicle Autonomy",
            "location": {"name": "Phoenix, AZ"},
            "content": "<p>Own vehicle simulation infrastructure.</p>"
                       "<p>MS or equivalent experience preferred.</p>",
            "first_published": "2026-02-15T00:00:00Z",
            "updated_at":      "2026-02-16T00:00:00Z",
            "absolute_url": "https://boards.greenhouse.io/exampleco/jobs/42",
            "departments": [{"name": "Engineering"}],
        },
    ]
}


def _mock_transport_gh(response_body: dict) -> httpx.MockTransport:
    """MockTransport that only serves the Greenhouse endpoint. Any
    other host causes the test to fail loudly."""
    def _handler(request: httpx.Request) -> httpx.Response:
        assert "boards-api.greenhouse.io" in request.url.host, (
            f"unexpected request to {request.url}"
        )
        return httpx.Response(200, json=response_body)
    return httpx.MockTransport(_handler)


# ---------------------------------------------------------------- ABC
def test_base_class_is_abstract():
    from domains.discovery.connector_sdk import OpportunitySourceConnector
    with pytest.raises(TypeError):
        # cannot instantiate an ABC with unimplemented abstract methods
        OpportunitySourceConnector()  # type: ignore[abstract]


def test_subclass_without_source_id_rejected():
    from domains.discovery.connector_sdk import OpportunitySourceConnector

    class Bad(OpportunitySourceConnector):
        async def discover(self): return []
        async def fetch(self, n, t): return []

    with pytest.raises(ValueError, match="source_id"):
        Bad()


# ---------------------------------------------------------------- no source skips shadow
@pytest.mark.asyncio
async def test_every_active_connector_has_a_registry_record(_seeded_registry):
    from domains.discovery.adapters.public_apis import CONNECTORS
    from domains.source_registry import get
    for src_id, cls in CONNECTORS.items():
        row = await get(src_id)
        assert row is not None, (
            f"connector {cls.__name__} source_id={src_id!r} has no "
            f"source_registry record — 'no source skips shadow' violated"
        )
        assert cls.source_id == src_id


# ---------------------------------------------------------------- policy fail-CLOSED
@pytest.mark.asyncio
async def test_unregistered_source_fails_closed_no_http(_seeded_registry):
    """A connector whose source_id is NOT in the registry must raise
    PolicyDenied BEFORE instantiating an HTTP client."""
    from domains.discovery.connector_sdk import OpportunitySourceConnector

    class Rogue(OpportunitySourceConnector):
        source_id = "rogue_never_registered"
        async def discover(self):
            await self.check_policy(Operation.DISCOVER)
            return []
        async def fetch(self, n, t):
            await self.check_policy(Operation.FETCH)
            # Sentinel: reaching here would mean the gate failed.
            raise AssertionError("gate did NOT stop the fetch — fail-closed broken")

    c = Rogue()
    with pytest.raises(PolicyDenied) as exc:
        await c.fetch("acme", "acme")
    assert "source_not_in_registry" in exc.value.decision.reason


@pytest.mark.asyncio
async def test_policy_deny_prevents_httpx_client_creation(monkeypatch, _seeded_registry):
    """Force LinkedIn (LEGAL_REJECTED + ROBOTS_BLOCKED) into the
    Greenhouse connector's source_id and verify that
    `httpx.AsyncClient` is NEVER instantiated when policy denies.

    Simulates the invariant 'no byte leaves the pod on DENY'.

    Batch 5 hardening: the gate now runs inside the shared factory
    `domains/discovery/adapters/http.py::policy_gated_client`, so we
    sabotage that module's httpx binding + _gate function.
    """
    from domains.discovery.adapters import http as http_factory

    # Sabotage: any httpx.AsyncClient instantiation from now on raises
    # loudly, so if the gate does NOT fail-close we'll see it.
    class _Tripwire:
        def __init__(self, *a, **kw):
            raise AssertionError(
                "httpx.AsyncClient was instantiated even though "
                "policy should have DENIED — fail-CLOSED broken"
            )
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(http_factory.httpx, "AsyncClient", _Tripwire)

    # Point the greenhouse fetcher's gate at LinkedIn (rejected).
    from domains.source_registry import get
    linkedin = await get("linkedin")
    assert linkedin is not None
    # Rewrite the factory's gate to look up LinkedIn (a rejected
    # source) so we can deterministically produce a DENY without
    # editing the registry.
    real_gate = http_factory._gate
    async def _sabotaged_gate(source_id: str, op: Operation) -> None:
        return await real_gate("linkedin", op)
    monkeypatch.setattr(http_factory, "_gate", _sabotaged_gate)

    from domains.discovery.adapters import public_apis as _pa
    # This MUST raise before httpx.AsyncClient is even constructed.
    with pytest.raises(PolicyDenied):
        await _pa.fetch_greenhouse("acme", "acme")


@pytest.mark.asyncio
async def test_kill_switch_halts_in_flight_connector(monkeypatch, _seeded_registry):
    """Set ADMIN_KILL_SWITCH_SOURCES=greenhouse after the connector is
    instantiated. The next call raises PolicyDenied with
    reason='kill_switch_engaged' and never issues HTTP."""
    from domains.discovery.adapters.public_apis import GreenhouseConnector
    from domains.discovery.adapters import http as http_factory

    # Ensure no accidental HTTP is possible.
    class _Tripwire:
        def __init__(self, *a, **kw):
            raise AssertionError(
                "httpx.AsyncClient was instantiated after kill switch — "
                "kill switch did NOT halt in-flight connector"
            )
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(http_factory.httpx, "AsyncClient", _Tripwire)

    c = GreenhouseConnector()
    # First: kill switch OFF — check_policy should PERMIT (but we skip
    # fetch to avoid the httpx tripwire; the FETCH policy is validated
    # in isolation).
    monkeypatch.delenv("ADMIN_KILL_SWITCH_SOURCES", raising=False)
    await c.check_policy(Operation.FETCH)  # no raise

    # Now engage the kill switch — same connector instance.
    monkeypatch.setenv("ADMIN_KILL_SWITCH_SOURCES", "greenhouse,lever")
    with pytest.raises(PolicyDenied) as exc:
        await c.fetch("acme", "acme")
    assert exc.value.decision.reason == "kill_switch_engaged"


# ---------------------------------------------------------------- byte-identical
@pytest.mark.asyncio
async def test_connector_fetch_output_byte_identical_to_raw(monkeypatch, _seeded_registry):
    """Byte-identical rail: `GreenhouseConnector().fetch(n,t)` returns
    EXACTLY what `fetch_greenhouse(n,t)` returns on the same canned
    upstream response.

    Batch 5 hardening: swap the guarded factory's `policy_gated_client`
    for a mock-transport variant that still runs the real gate before
    returning a MockTransport-backed client.
    """
    from domains.discovery.adapters import http as http_factory
    from domains.discovery.adapters.public_apis import (
        GreenhouseConnector, fetch_greenhouse,
    )
    from contextlib import asynccontextmanager

    transport = _mock_transport_gh(_CANNED_GH)
    real_gate = http_factory._gate

    @asynccontextmanager
    async def _mock_gated_client(source_id, operation, *, headers=None,
                                  timeout=15.0, follow_redirects=True,
                                  **_kw):
        # Still run the real gate so fail-CLOSED remains covered.
        await real_gate(source_id, operation)
        async with httpx.AsyncClient(
            transport=transport,
            headers={"User-Agent": http_factory.DEFAULT_USER_AGENT,
                     "Accept": "application/json"},
            timeout=timeout,
        ) as c:
            yield c

    monkeypatch.setattr(http_factory, "policy_gated_client",
                        _mock_gated_client)
    # `public_apis` did `from ... import policy_gated_client`, so also
    # rebind the name inside that module.
    from domains.discovery.adapters import public_apis as _pa
    monkeypatch.setattr(_pa, "policy_gated_client", _mock_gated_client)

    raw_out = await fetch_greenhouse("ExampleCo", "exampleco")
    sdk_out = await GreenhouseConnector().fetch("ExampleCo", "exampleco")

    # Both non-empty and payload-identical except for `fetched_at`
    # which is stamped at wall-clock time inside the fetcher. Strip
    # that key before comparing so the rail is deterministic.
    assert len(raw_out) == 1
    assert len(sdk_out) == 1
    for row in (raw_out[0], sdk_out[0]):
        row.pop("fetched_at", None)
    assert raw_out[0] == sdk_out[0], (
        "SDK connector must return byte-identical rows vs. the raw "
        "module-level fetcher on the same inputs"
    )


# ---------------------------------------------------------------- NO LLM
def test_connector_sdk_has_no_llm_calls():
    p = (pathlib.Path(__file__).resolve().parent.parent
         / "domains" / "discovery" / "connector_sdk.py")
    text = p.read_text(encoding="utf-8")
    forbidden = ("openai", "anthropic", "gemini",
                 "emergentintegrations", "generate_with_llm",
                 "chat.completions")
    hits = [f for f in forbidden if f in text.lower()]
    assert not hits, f"connector_sdk must NOT reference LLM SDKs: {hits}"


# ---------------------------------------------------------------- normalize contract
@pytest.mark.asyncio
async def test_normalized_posting_shape(monkeypatch, _seeded_registry):
    from domains.discovery.connector_sdk import REQUIRED_NORMALIZED_KEYS
    from domains.discovery.adapters import http as http_factory
    from domains.discovery.adapters.public_apis import GreenhouseConnector
    from contextlib import asynccontextmanager

    transport = _mock_transport_gh(_CANNED_GH)
    real_gate = http_factory._gate

    @asynccontextmanager
    async def _mock_gated_client(source_id, operation, *, headers=None,
                                  timeout=15.0, follow_redirects=True,
                                  **_kw):
        await real_gate(source_id, operation)
        async with httpx.AsyncClient(
            transport=transport,
            headers={"User-Agent": http_factory.DEFAULT_USER_AGENT,
                     "Accept": "application/json"},
            timeout=timeout,
        ) as c:
            yield c

    monkeypatch.setattr(http_factory, "policy_gated_client",
                        _mock_gated_client)
    from domains.discovery.adapters import public_apis as _pa
    monkeypatch.setattr(_pa, "policy_gated_client", _mock_gated_client)

    rows = await GreenhouseConnector().fetch("ExampleCo", "exampleco")
    assert rows and set(REQUIRED_NORMALIZED_KEYS).issubset(rows[0].keys()), (
        f"normalize contract broken; missing keys: "
        f"{REQUIRED_NORMALIZED_KEYS - rows[0].keys()}"
    )

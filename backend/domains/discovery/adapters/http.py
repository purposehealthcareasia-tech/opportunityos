"""P1 FOUNDATION Batch 5 · Hardening · Single guarded httpx factory for
discovery adapters.

Before this module, each discovery adapter constructed its own
`httpx.AsyncClient(...)` immediately after calling
`source_policy.allow(...).raise_if_denied()`. That worked, but the
tripwire (`test_no_raw_httpx_asyncclient_outside_guarded_paths`) had to
allowlist EVERY discovery adapter file by name, so every new adapter
would need a per-module review — the tripwire's structural guarantee
was leaking.

This factory removes the escape:

  * `policy_gated_client(source_id, operation, ...)` is the ONE
    entry-point that constructs an `httpx.AsyncClient` inside
    `domains/discovery/`.
  * It runs the policy gate FIRST (fail-CLOSED, kill-switch honored),
    then yields a configured client via `asynccontextmanager`.
  * Every discovery adapter uses `async with policy_gated_client(...)
    as c:` instead of raw `httpx.AsyncClient(...)`.
  * Test `test_no_raw_httpx_under_discovery` asserts that no other file
    under `domains/discovery/` constructs `httpx.AsyncClient(`. Adding
    a new adapter cannot bypass the gate — the tripwire fails at the
    grep level before code review.

Rails:
  * The policy gate runs once, at client-construction time. It does
    NOT persist across the client's lifetime, so if the founder toggles
    the kill switch mid-fetch, the NEXT `policy_gated_client(...)` call
    fails-CLOSED at the next hop. This mirrors the pre-hardening
    behavior — no regression.
  * The factory does not implement SSRF / rebinding defenses; discovery
    adapters hit KNOWN, FIXED vendor hosts (greenhouse, lever, ashby,
    usajobs) documented in the source registry. Hostile-content defense
    (`safe_fetch`) is for opportunity-body ingestion where the URL is
    caller-supplied.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx

from domains.source_policy import Operation


DEFAULT_USER_AGENT = "LYNK-Autopilot/preview (contact: privacy@fynd.llc)"
DEFAULT_TIMEOUT_S: float = 15.0


async def _gate(source_id: str, operation: Operation) -> None:
    """Deferred imports mirror `public_apis._gate` — avoids a circular
    import chain through `discovery/service.py` at module load time.
    Raises `PolicyDenied` on any DENY (kill-switch, unregistered
    source, denied op). No cache."""
    from domains.source_policy import PolicyDecision, PolicyDenied, allow
    from domains.source_registry import get as _reg_get
    from core.time_utils import utc_now

    rec = await _reg_get(source_id)
    if rec is None:
        raise PolicyDenied(PolicyDecision(
            allowed=False,
            reason="source_not_in_registry",
            source_id=source_id,
            operation=operation.value if hasattr(operation, "value") else str(operation),
            evaluated_at=utc_now().isoformat(),
            field_values={},
        ))
    allow(source_record=rec, operation=operation).raise_if_denied()


@asynccontextmanager
async def policy_gated_client(
    source_id: str,
    operation: Operation,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    follow_redirects: bool = True,
    **extra_client_kwargs: Any,
) -> AsyncIterator[httpx.AsyncClient]:
    """The ONE guarded entry-point for `httpx.AsyncClient` inside
    `domains/discovery/`.

    Contract:
      * Gate runs BEFORE client construction. If DENY, raises
        `PolicyDenied` and never opens a socket.
      * On ALLOW, yields a configured `httpx.AsyncClient` with a polite
        default UA and 15s timeout.
      * Caller may pass `headers=` to override/extend defaults (e.g.
        USAJOBS `Authorization-Key`). Explicit UA in caller headers
        wins; otherwise the polite default is applied.
      * Caller may pass any additional `httpx.AsyncClient` kwargs.
    """
    await _gate(source_id, operation)
    merged_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
    if headers:
        merged_headers.update(headers)
    async with httpx.AsyncClient(
        headers=merged_headers,
        timeout=timeout,
        follow_redirects=follow_redirects,
        **extra_client_kwargs,
    ) as c:
        yield c

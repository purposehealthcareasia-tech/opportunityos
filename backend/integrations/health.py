"""Integration health-check runner + event logger.

Persists provider status/latency snapshots into Mongo:
  - `integration_configs` : one row per provider, current state.
  - `integration_events`  : append-only ledger — status transitions, errors,
                             successful test-connections, admin toggles.
"""
from __future__ import annotations

import time
import uuid

from core.db import get_db
from core.time_utils import utc_now

from integrations.base import BaseProvider, HealthResult, ProviderStatus


async def snapshot_provider(p: BaseProvider) -> dict:
    """Refresh `integration_configs` for `p` — non-destructive upsert."""
    d = p.describe()
    row = {
        "slug": p.slug,
        "label": p.label,
        "category": d["category"],
        "status": d["status"],
        "is_test_mode": d["is_test_mode"],
        "missing_env": d["missing_env"],
        "required_env": d["required_env"],
        "optional_env": d["optional_env"],
        "docs_url": p.docs_url,
        "updated_at": utc_now(),
    }
    await get_db().integration_configs.update_one(
        {"slug": p.slug},
        {"$set": row, "$setOnInsert": {"created_at": utc_now()}},
        upsert=True,
    )
    return row


async def record_event(*, provider: str, kind: str, detail: dict | None = None,
                        actor: str | None = None) -> str:
    """Append an entry to `integration_events`. `kind` examples:
       status_transition, test_connection_ok, test_connection_fail, admin_enable,
       admin_disable, webhook_received, external_error, health_check_ok."""
    row = {
        "id": str(uuid.uuid4()),
        "provider": provider,
        "kind": kind,
        "detail": detail or {},
        "actor": actor,
        "ts": utc_now(),
    }
    await get_db().integration_events.insert_one(row)
    return row["id"]


async def run_health_checks(providers: list[BaseProvider]) -> dict[str, HealthResult]:
    """Runs `health_check()` on every provider. Result is persisted per-provider.
    Returns a dict {slug: HealthResult}. Non-blocking failures — health failure
    on one provider must never break the loop."""
    results: dict[str, HealthResult] = {}
    for p in providers:
        try:
            t0 = time.time()
            res = await p.health_check()
            if res.latency_ms is None:
                res.latency_ms = int((time.time() - t0) * 1000)
            results[p.slug] = res
            if res.healthy:
                p.record_success()
            await snapshot_provider(p)
            await record_event(
                provider=p.slug,
                kind="health_check_ok" if res.healthy else "health_check_fail",
                detail={"latency_ms": res.latency_ms, "error": res.error},
            )
        except Exception as e:
            results[p.slug] = HealthResult(healthy=False, error=str(e)[:200])
            await record_event(provider=p.slug, kind="health_check_error",
                                detail={"error": str(e)[:200]})
    return results


async def ensure_indexes() -> None:
    db = get_db()
    await db.integration_configs.create_index("slug", unique=True)
    await db.integration_configs.create_index("category")
    await db.integration_events.create_index([("provider", 1), ("ts", -1)])
    await db.integration_events.create_index("ts")
    # `webhook_events` — deduped by (provider, external_event_id).
    await db.webhook_events.create_index(
        [("provider", 1), ("external_event_id", 1)], unique=True,
        partialFilterExpression={"external_event_id": {"$exists": True, "$type": "string"}},
    )
    await db.webhook_events.create_index("ts")

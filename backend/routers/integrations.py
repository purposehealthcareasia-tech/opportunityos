"""Admin integrations dashboard router.

Founder mandate — Milestone A. Endpoints:
  GET   /api/v1/admin/integrations              — list every registered provider with status
  GET   /api/v1/admin/integrations/{slug}       — detail incl. recent events
  POST  /api/v1/admin/integrations/{slug}/test  — trigger provider.test_connection()
  POST  /api/v1/admin/integrations/{slug}/enable
  POST  /api/v1/admin/integrations/{slug}/disable

All endpoints require the admin OR support role for reads; admin-only for
writes (enable / disable / test-connection). Every write records an
`integration_events` row.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.db import get_db
from core.deps import get_current_user
from domains.admin.service import _require_admin, _require_admin_only
from domains.audit import service as audit
from integrations import registry, health as integrations_health


router = APIRouter(prefix="/api/v1/admin/integrations", tags=["admin:integrations"])


@router.get("")
async def list_integrations(staff: dict = Depends(_require_admin)):
    """Admin/support read: describe every registered provider. Never leaks
    secret material — `describe()` omits config values."""
    providers = [p.describe() for p in registry.all_providers()]
    providers.sort(key=lambda p: (p["category"] or "", p["label"]))
    return {"providers": providers, "summary": registry.summary()}


@router.get("/{slug}")
async def get_integration(slug: str, staff: dict = Depends(_require_admin)):
    p = registry.get(slug)
    if not p:
        raise HTTPException(status_code=404, detail={"error": "provider_not_found"})
    d = p.describe()
    # Recent events for this provider.
    cur = get_db().integration_events.find(
        {"provider": slug}, {"_id": 0},
    ).sort("ts", -1).limit(20)
    d["recent_events"] = [e async for e in cur]
    # Persisted config row (idempotent).
    await integrations_health.snapshot_provider(p)
    return d


@router.post("/{slug}/test")
async def test_integration(slug: str, staff: dict = Depends(_require_admin_only)):
    p = registry.get(slug)
    if not p:
        raise HTTPException(status_code=404, detail={"error": "provider_not_found"})
    result = await p.test_connection()
    kind = "test_connection_ok" if result.ok else "test_connection_fail"
    await integrations_health.record_event(
        provider=slug, kind=kind, actor=staff["id"],
        detail={"latency_ms": result.latency_ms, "detail": result.detail},
    )
    await integrations_health.snapshot_provider(p)
    await audit.write(staff["id"], f"admin.integration.{kind}",
                       f"provider:{slug}", {"detail": result.detail})
    return {
        "ok": result.ok,
        "detail": result.detail,
        "latency_ms": result.latency_ms,
        "status": p.status().value,
    }


@router.post("/{slug}/enable")
async def enable_integration(slug: str, staff: dict = Depends(_require_admin_only)):
    p = registry.get(slug)
    if not p:
        raise HTTPException(status_code=404, detail={"error": "provider_not_found"})
    p.enable()
    await integrations_health.record_event(
        provider=slug, kind="admin_enable", actor=staff["id"],
    )
    await integrations_health.snapshot_provider(p)
    await audit.write(staff["id"], "admin.integration.enable", f"provider:{slug}", {})
    return {"slug": slug, "status": p.status().value}


@router.post("/{slug}/disable")
async def disable_integration(slug: str, staff: dict = Depends(_require_admin_only)):
    p = registry.get(slug)
    if not p:
        raise HTTPException(status_code=404, detail={"error": "provider_not_found"})
    p.disable()
    await integrations_health.record_event(
        provider=slug, kind="admin_disable", actor=staff["id"],
    )
    await integrations_health.snapshot_provider(p)
    await audit.write(staff["id"], "admin.integration.disable", f"provider:{slug}", {})
    return {"slug": slug, "status": p.status().value}

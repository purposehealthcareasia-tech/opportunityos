"""Milestone B — storage backend regression.

Ensures:
  1. `services.storage.storage` selects the right backend based on env vars.
  2. Round-trip put/get works on whichever backend is active.
  3. `MediaStorageProvider.describe()` reflects the actual runtime state and
     never leaks secret values.
  4. Provider `test_connection()` returns ok=True on the live backend.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest


@pytest.fixture(scope="module")
def storage_backend():
    # Ensure adapter modules register with the registry (server lifespan is
    # not started during unit-only pytest runs).
    from integrations import registry
    registry.load_all()
    from services.storage import storage
    return storage


def test_backend_selected_matches_env(storage_backend):
    """Auto-selection: Emergent when EMERGENT_LLM_KEY set + no explicit
    MEDIA_STORAGE_BACKEND=local override, else local disk."""
    from services.storage import EmergentObjectStorage, LocalDiskStorage
    explicit = (os.environ.get("MEDIA_STORAGE_BACKEND") or "").strip().lower()
    emergent_key = bool(os.environ.get("EMERGENT_LLM_KEY"))
    if explicit == "local" or not emergent_key:
        assert isinstance(storage_backend, LocalDiskStorage)
    else:
        assert isinstance(storage_backend, EmergentObjectStorage)


@pytest.mark.asyncio
async def test_put_get_roundtrip(storage_backend):
    """Whatever backend is live must satisfy the same put/get contract."""
    key = f"milestone_b/probe-{uuid.uuid4()}.bin"
    payload = b"milestone-b-payload"
    meta = await storage_backend.put(key, payload, content_type="application/octet-stream")
    assert meta["size"] == len(payload)
    assert meta["sha256"]  # non-empty hex
    got = await storage_backend.get(meta["s3_key"] or key)
    assert got == payload


def test_media_storage_provider_describe_never_leaks_secrets():
    from integrations import registry
    registry.load_all()
    p = registry.get("media_storage")
    assert p is not None
    d = p.describe()
    # No secret values — only env-var NAMES.
    for env_name in ("EMERGENT_LLM_KEY", "MEDIA_STORAGE_BACKEND"):
        val = os.environ.get(env_name) or ""
        if val:
            body = repr(d)
            assert val not in body, f"provider.describe() leaked value of {env_name}"


@pytest.mark.asyncio
async def test_media_storage_provider_test_connection_ok():
    """When the runtime is properly configured, `test_connection()` must
    return ok=True and a non-empty detail string."""
    from integrations import registry
    registry.load_all()
    p = registry.get("media_storage")
    result = await p.test_connection()
    assert result.ok, f"expected ok=True, got {result.detail}"
    assert result.detail

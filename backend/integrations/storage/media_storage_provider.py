"""Media storage provider — Emergent-managed object storage (Milestone B).

Implements the playbook flow (`init` → session-scoped X-Storage-Key → PUT/GET
by path). Status matrix:

  - CONFIGURATION_REQUIRED: EMERGENT_LLM_KEY not set AND MEDIA_STORAGE_BACKEND
    != "local".
  - TEST_MODE: EMERGENT_LLM_KEY present. Emergent object storage runs on the
    shared preview surface, so we never claim CONNECTED for it.
  - CONNECTED: reserved for future dedicated buckets.

Secrets NEVER leak into the admin dashboard: `describe()` only ever emits
env-var *names*.
"""
from __future__ import annotations

import os
import time

from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult, ConfigValidation,
)
from integrations import registry


class MediaStorageProvider(BaseProvider):
    slug = "media_storage"
    label = "Media storage (Emergent object storage)"
    category = ProviderCategory.STORAGE
    required_env = ("EMERGENT_LLM_KEY",)
    optional_env = ("MEDIA_STORAGE_BACKEND",)
    docs_url = ""
    supports_test_mode = True

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        # Emergent object storage is always the shared preview surface.
        return bool(self.config.get("EMERGENT_LLM_KEY"))

    def validate_configuration(self) -> ConfigValidation:
        # If the operator has explicitly forced the local disk backend, the
        # emergent key is not required and status flips to TEST_MODE-under-local
        # (we still surface EMERGENT_LLM_KEY as required for the production
        # backend so ops knows what to provision).
        backend = (self.config.get("MEDIA_STORAGE_BACKEND") or "").strip().lower()
        if backend == "local":
            return ConfigValidation(ok=True, is_test_mode=True,
                                     note="Local disk backend selected. Emergent object storage available on key.")
        missing = [k for k in self.required_env if not self.config.get(k)]
        if missing:
            return ConfigValidation(ok=False, missing_env=missing,
                                     note="Set EMERGENT_LLM_KEY to use Emergent object storage.")
        return ConfigValidation(ok=True, is_test_mode=True,
                                 note="Emergent object storage session initialises on first use.")

    async def health_check(self) -> HealthResult:
        # Cheap probe: ensure the singleton `services.storage.storage` has the
        # expected backend name. Do NOT hit the network here — health_check must
        # be sub-2s and side-effect-free.
        try:
            from services.storage import storage
            backend = getattr(storage, "backend_name", "unknown")
            return HealthResult(healthy=True,
                                 latency_ms=0,
                                 error=None if backend != "unknown" else f"unknown backend")
        except Exception as e:
            return HealthResult(healthy=False, error=str(e)[:200])

    async def test_connection(self) -> TestResult:
        """Admin action — deeper probe. For Emergent it calls `/init` to make
        sure the credential works. Local disk simply confirms the writable root."""
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        try:
            from services.storage import storage, EmergentObjectStorage, LocalDiskStorage
            t0 = time.time()
            if isinstance(storage, EmergentObjectStorage):
                # Force a fresh /init round-trip.
                storage._init_key(force=True)
                latency_ms = int((time.time() - t0) * 1000)
                return TestResult(ok=True, detail="Emergent /init OK.",
                                   latency_ms=latency_ms,
                                   raw={"backend": "emergent"})
            if isinstance(storage, LocalDiskStorage):
                # Write + read a tiny probe object.
                probe_key = "__integration_probe__/test.txt"
                await storage.put(probe_key, b"probe", content_type="text/plain")
                _ = await storage.get(probe_key)
                latency_ms = int((time.time() - t0) * 1000)
                return TestResult(ok=True, detail="Local disk probe OK.",
                                   latency_ms=latency_ms,
                                   raw={"backend": "local"})
            return TestResult(ok=True, detail="Unknown storage backend.")
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_failed: {str(e)[:200]}")


registry.register(MediaStorageProvider())

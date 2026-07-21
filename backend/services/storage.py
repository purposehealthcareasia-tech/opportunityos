"""Storage service — unified surface with two concrete backends.

Milestone B of the founder integrations mandate promotes the storage adapter
to a real Emergent-managed object-storage backend by default. Local disk stays
as a labeled fallback for the case where `EMERGENT_LLM_KEY` is absent (dev
containers without the universal key). Both backends implement the same
`StorageService` protocol so `domains/documents/service.py` and
`domains/applications/service.py` remain untouched.

Selection order:
1. `MEDIA_STORAGE_BACKEND` env var when explicitly set (`emergent` | `local`).
2. `emergent` when `EMERGENT_LLM_KEY` is present.
3. `local` otherwise.

The Emergent object-storage playbook has hard constraints:
    - No delete API (soft-delete lives in the DB layer).
    - No presigned URLs — all downloads are proxied by the backend.
    - `storage_key` is session-scoped — re-`/init` on 403 or first use.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Protocol

import requests

from core.config import settings


log = logging.getLogger("oppos.storage")

# Ensure backend/.env is loaded so both the running server and standalone unit
# tests select the same backend.
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env, override=False)
except Exception:
    pass


class StorageService(Protocol):
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> dict: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# Local disk (dev / fallback) — original v0.1 behaviour, unchanged surface.
# ---------------------------------------------------------------------------
class LocalDiskStorage:
    """Backwards-compatible v0.1 local disk backend.

    Documents rows still carry `s3_key + sha256` so this stays wire-compatible
    with the Emergent backend below.
    """

    backend_name = "local"

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.STORAGE_ROOT)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("invalid_key")
        return p

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> dict:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {
            "s3_key": key,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "content_type": content_type,
            "backend": self.backend_name,
        }

    async def get(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            os.remove(path)


# ---------------------------------------------------------------------------
# Emergent object storage (default when EMERGENT_LLM_KEY is available).
# ---------------------------------------------------------------------------
_EMERGENT_STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
_APP_PREFIX = "opportunityos"


class EmergentStorageError(Exception):
    """Raised when the Emergent storage backend is unreachable / mis-configured."""


class EmergentObjectStorage:
    """Emergent-managed object storage — playbook implementation.

    Constraints from the playbook:
      - `storage_key` is session-scoped; init once, refresh on 403.
      - No delete / no rename / no presigned URLs.
      - Paths must be prefixed to avoid bucket collisions.
    """

    backend_name = "emergent"

    def __init__(self, emergent_key: str, *, storage_url: str = _EMERGENT_STORAGE_URL,
                 app_prefix: str = _APP_PREFIX):
        if not emergent_key:
            raise ValueError("EMERGENT_LLM_KEY is required for the Emergent object storage backend.")
        self._emergent_key = emergent_key
        self._storage_url = storage_url.rstrip("/")
        self._app_prefix = app_prefix.strip("/")
        self._storage_key: str | None = None
        self._lock = threading.Lock()

    # ---- session key -----------------------------------------------------

    def _init_key(self, *, force: bool = False) -> str:
        with self._lock:
            if self._storage_key and not force:
                return self._storage_key
            try:
                r = requests.post(
                    f"{self._storage_url}/init",
                    json={"emergent_key": self._emergent_key},
                    timeout=30,
                )
                r.raise_for_status()
                self._storage_key = r.json()["storage_key"]
                log.info("Emergent object storage session initialised.")
                return self._storage_key
            except Exception as e:  # pragma: no cover — network conditions
                raise EmergentStorageError(f"init_failed: {e}") from e

    def _headers(self, *, content_type: str | None = None) -> dict:
        h = {"X-Storage-Key": self._init_key()}
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _prefixed(self, key: str) -> str:
        k = key.lstrip("/")
        if k.startswith(self._app_prefix + "/"):
            return k
        return f"{self._app_prefix}/{k}"

    # ---- protocol implementation ----------------------------------------

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> dict:
        path = self._prefixed(key)
        content_type = content_type or "application/octet-stream"

        def _do_put():
            return requests.put(
                f"{self._storage_url}/objects/{path}",
                headers=self._headers(content_type=content_type),
                data=data,
                timeout=120,
            )

        r = _do_put()
        if r.status_code == 403:
            # Refresh session key + retry once.
            self._init_key(force=True)
            r = _do_put()
        if r.status_code == 409:
            # Path already exists — treat as idempotent write success. Documents
            # module de-dupes by sha, so this only fires when the exact same key
            # is written twice (safe).
            log.info("Emergent storage PUT 409 (already exists) — treating as success. key=%s", path)
        elif not r.ok:
            raise EmergentStorageError(f"put_failed: HTTP {r.status_code} {r.text[:200]}")

        body = {}
        try:
            body = r.json()
        except Exception:
            pass
        return {
            "s3_key": body.get("path") or path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": body.get("size", len(data)),
            "content_type": content_type,
            "etag": body.get("etag"),
            "backend": self.backend_name,
        }

    async def get(self, key: str) -> bytes:
        path = self._prefixed(key)

        def _do_get():
            return requests.get(
                f"{self._storage_url}/objects/{path}",
                headers=self._headers(),
                timeout=60,
            )

        r = _do_get()
        if r.status_code == 403:
            self._init_key(force=True)
            r = _do_get()
        if r.status_code == 404:
            raise EmergentStorageError(f"not_found: {path}")
        if not r.ok:
            raise EmergentStorageError(f"get_failed: HTTP {r.status_code}")
        return r.content

    async def delete(self, key: str) -> None:
        """Emergent has no delete API — soft-delete is handled at the DB layer.

        Kept for interface parity. Callers must NOT rely on this to enforce
        privacy hard-delete; use the `is_deleted=true` flag on `documents` /
        `media_files` and the periodic purge routine (Milestone B++).
        """
        log.debug("EmergentObjectStorage.delete(%s) is a no-op (playbook constraint).", key)
        return None


# ---------------------------------------------------------------------------
# Backend selection.
# ---------------------------------------------------------------------------
def _select_backend() -> StorageService:
    explicit = (os.environ.get("MEDIA_STORAGE_BACKEND") or "").strip().lower()
    emergent_key = os.environ.get("EMERGENT_LLM_KEY", "")

    if explicit == "local":
        return LocalDiskStorage()
    if explicit == "emergent":
        if not emergent_key:
            log.warning("MEDIA_STORAGE_BACKEND=emergent but EMERGENT_LLM_KEY unset — falling back to local disk.")
            return LocalDiskStorage()
        return EmergentObjectStorage(emergent_key)

    # Auto: prefer Emergent when key is present, else local.
    if emergent_key:
        try:
            return EmergentObjectStorage(emergent_key)
        except Exception:
            log.exception("Emergent storage init failed — falling back to local disk.")
            return LocalDiskStorage()
    return LocalDiskStorage()


storage: StorageService = _select_backend()

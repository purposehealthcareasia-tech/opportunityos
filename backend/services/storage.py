"""Storage service — local disk implementation behind an S3-compatible surface.

All storage in Phase 1 lands on the container's local disk under STORAGE_ROOT.
Documents records still carry `s3_key` and `sha256` so later phases can swap in real S3 without
touching callers.
"""
import hashlib
import os
from pathlib import Path
from typing import Protocol
from core.config import settings


class StorageService(Protocol):
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> dict: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class LocalDiskStorage:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.STORAGE_ROOT)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Prevent traversal.
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
        }

    async def get(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            os.remove(path)


storage: StorageService = LocalDiskStorage()

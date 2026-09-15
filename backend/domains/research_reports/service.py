"""Private account storage for inert, compact research bundles.

The owner argument must come from authenticated backend state, never from a
request body. One Mongo document is one owner bucket. Conditional updates reserve
quota and append/remove a report atomically; no count-then-insert quota decisions.
Canonical payloads total at most 10 MiB, leaving ample space under Mongo's 16 MiB
document limit for at most 20 bounded metadata records. No fetch, disk I/O, HTML
rendering, parser interpretation, logging, or job/application action occurs here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any


MIB = 1024 * 1024
MAX_REPORT_BYTES = 8 * MIB
MAX_TOTAL_BYTES = 10 * MIB
MAX_REPORTS = 20
FILES = ("evidence.jsonl", "candidates.jsonl", "outcomes.jsonl", "edges.jsonl")
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
OWNER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
UNSAFE_KEYS = {"__proto__", "constructor", "prototype", "owner", "ownerId", "owner_id", "userId", "user_id", "tenantId", "tenant_id"}


class ResearchReportError(RuntimeError):
    """Safe code/status only; never an upstream message or report content."""

    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__("Research report storage request could not be completed.")


def _invalid() -> None:
    raise ResearchReportError("RESEARCH_REPORT_INVALID", 400)


def _not_found() -> None:
    raise ResearchReportError("RESEARCH_REPORT_NOT_FOUND", 404)


def _owner(value: Any) -> str:
    if not isinstance(value, str) or not OWNER_PATTERN.fullmatch(value):
        _invalid()
    return value


def _report_id(value: Any) -> str:
    if not isinstance(value, str) or not UUID_PATTERN.fullmatch(value):
        _invalid()
    return value.lower()


def _utf8(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeError:
        _invalid()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError, UnicodeError):
        _invalid()


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _decode(value: str) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_json_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, RecursionError):
        _invalid()


def _bundle(value: Any, maximum: int) -> tuple[str, int, str]:
    if type(value) is not dict or set(value) != {"manifest", "files"}:
        _invalid()
    manifest, files = value["manifest"], value["files"]
    if type(manifest) is not dict or set(manifest) - {"schemaVersion", "title", "omissions", "warnings", "runSummary"}:
        _invalid()
    if type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1:
        _invalid()
    title = manifest.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 500 or re.search(r"[\x00-\x1f\x7f]", title):
        _invalid()
    for key in ("omissions", "warnings"):
        rows = manifest.get(key)
        if type(rows) is not list or len(rows) > 1000 or any(not isinstance(row, str) or len(row) > 1000 for row in rows):
            _invalid()
    if "runSummary" in manifest and type(manifest["runSummary"]) is not dict:
        _invalid()
    if type(files) is not dict or set(files) != set(FILES):
        _invalid()
    if any(not isinstance(body, str) for body in files.values()):
        _invalid()
    # Bound raw strings before parsing their JSONL contents or canonicalizing.
    if sum(len(body) for body in files.values()) > maximum:
        raise ResearchReportError("RESEARCH_REPORT_TOO_LARGE", 413)
    nodes = 0

    def inspect(item: Any, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 150000 or depth > 20:
            _invalid()
        if type(item) is dict:
            for key, child in item.items():
                if not isinstance(key, str) or key in UNSAFE_KEYS or len(key) > 500:
                    _invalid()
                _utf8(key)
                inspect(child, depth + 1)
        elif type(item) is list:
            if len(item) > 5000:
                _invalid()
            for child in item:
                inspect(child, depth + 1)
        elif item is not None and type(item) not in (str, int, float, bool):
            _invalid()
        elif type(item) is float and not math.isfinite(item):
            _invalid()
        elif type(item) is str:
            # JSON escape sequences can decode to invalid lone surrogates even
            # when the enclosing JSONL text itself is valid UTF-8.
            _utf8(item)

    inspect(value)
    serialized = _canonical(value)
    size = len(_utf8(serialized))
    if size > maximum:
        raise ResearchReportError("RESEARCH_REPORT_TOO_LARGE", 413)
    counts = {}
    for name in FILES:
        # One blank trailing line is normal JSONL. Blank lines never count as
        # records, but the serialized-byte limit still charges for all of them.
        # Only LF separates JSONL records. Unicode line separators may legally
        # occur inside JSON strings and must not be mistaken for record breaks.
        lines = [line for line in files[name].split("\n") if line.strip()]
        limit = 1000 if name == "evidence.jsonl" else 5000
        if len(lines) > limit:
            _invalid()
        counts[name] = len(lines)
        for line in lines:
            row = _decode(line)
            if type(row) is not dict:
                _invalid()
            inspect(row)
    if sum(counts[name] for name in FILES[1:]) > 5000:
        _invalid()
    if not counts[FILES[0]] and "runSummary" not in manifest:
        _invalid()
    return serialized, size, title


def _metadata(record: dict) -> dict:
    return {key: record[key] for key in ("id", "title", "saved_at", "byte_size")}


class ResearchReportService:
    def __init__(self, collection, *, max_snapshot_bytes: int = MAX_REPORT_BYTES,
                 max_owner_bytes: int = MAX_TOTAL_BYTES, max_reports: int = MAX_REPORTS,
                 now=None, id_factory=None):
        for value, maximum in ((max_snapshot_bytes, MAX_REPORT_BYTES), (max_owner_bytes, MAX_TOTAL_BYTES), (max_reports, MAX_REPORTS)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ResearchReportError("RESEARCH_REPORT_CONFIGURATION", 500)
        if collection is None or (now is not None and not callable(now)) or (id_factory is not None and not callable(id_factory)):
            raise ResearchReportError("RESEARCH_REPORT_CONFIGURATION", 500)
        self.collection = collection
        self.max_snapshot_bytes = max_snapshot_bytes
        self.max_owner_bytes = max_owner_bytes
        self.max_reports = max_reports
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.id_factory = id_factory or uuid.uuid4

    @property
    def limits(self) -> dict:
        return {"max_reports": self.max_reports, "max_report_bytes": self.max_snapshot_bytes, "max_total_bytes": self.max_owner_bytes}

    async def _call(self, method: str, *args, **kwargs):
        try:
            return await getattr(self.collection, method)(*args, **kwargs)
        except ResearchReportError:
            raise
        except Exception:
            raise ResearchReportError("RESEARCH_REPORT_STORAGE_UNAVAILABLE", 503) from None

    async def _ensure(self, owner: str) -> None:
        try:
            await self.collection.update_one({"_id": owner}, {"$setOnInsert": {
                "schema_version": 1, "used_bytes": 0, "reports": []}}, upsert=True)
        except Exception as failure:
            # Concurrent first upserts can race on Mongo's unique _id index.
            # Only that known collision is benign; later reads verify the bucket.
            if getattr(failure, "code", None) != 11000:
                raise ResearchReportError("RESEARCH_REPORT_STORAGE_UNAVAILABLE", 503) from None

    async def _read(self, owner: str) -> dict | None:
        bucket = await self._call("find_one", {"_id": owner})
        if bucket is None:
            return None
        try:
            if type(bucket) is not dict or set(bucket) != {"_id", "schema_version", "used_bytes", "reports"} or bucket["_id"] != owner or type(bucket["schema_version"]) is not int or bucket["schema_version"] != 1:
                _invalid()
            reports, used = bucket["reports"], bucket["used_bytes"]
            if type(reports) is not list or len(reports) > MAX_REPORTS or type(used) is not int or not 0 <= used <= MAX_TOTAL_BYTES:
                _invalid()
            total, ids, hashes = 0, set(), set()
            for record in reports:
                if type(record) is not dict or set(record) != {"id", "title", "saved_at", "byte_size", "content_hash", "payload"}:
                    _invalid()
                report_id = _report_id(record["id"])
                if report_id != record["id"] or report_id in ids or not isinstance(record["content_hash"], str) or not HASH_PATTERN.fullmatch(record["content_hash"]) or record["content_hash"] in hashes:
                    _invalid()
                ids.add(report_id); hashes.add(record["content_hash"])
                if not isinstance(record["payload"], str) or len(record["payload"]) > MAX_REPORT_BYTES or type(record["byte_size"]) is not int or not 0 < record["byte_size"] <= MAX_REPORT_BYTES:
                    _invalid()
                raw = _utf8(record["payload"])
                total += len(raw)
                if total > MAX_TOTAL_BYTES or len(raw) != record["byte_size"] or hashlib.sha256(raw).hexdigest() != record["content_hash"]:
                    _invalid()
                payload, size, title = _bundle(_decode(record["payload"]), MAX_REPORT_BYTES)
                if payload != record["payload"] or size != record["byte_size"] or title != record["title"]:
                    _invalid()
                saved_at = record["saved_at"]
                if not isinstance(saved_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", saved_at):
                    _invalid()
                datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
            if total != used:
                _invalid()
            return bucket
        except (ResearchReportError, TypeError, ValueError, KeyError, RecursionError, UnicodeError):
            raise ResearchReportError("RESEARCH_REPORT_STORAGE_INVALID", 503) from None

    async def save(self, owner, bundle) -> dict:
        owner = _owner(owner)
        payload, byte_size, title = _bundle(bundle, self.max_snapshot_bytes)
        digest = hashlib.sha256(_utf8(payload)).hexdigest()
        await self._ensure(owner)
        # Retry only atomic-filter contention, never network requests. A failed
        # response can safely be retried by payload hash without allocating again.
        for _ in range(3):
            bucket = await self._read(owner)
            if bucket is None:
                raise ResearchReportError("RESEARCH_REPORT_STORAGE_UNAVAILABLE", 503)
            duplicate = next((row for row in bucket["reports"] if row["content_hash"] == digest), None)
            if duplicate:
                if duplicate["payload"] != payload:
                    raise ResearchReportError("RESEARCH_REPORT_STORAGE_INVALID", 503)
                return {"report": _metadata(duplicate), "replay": True}
            try:
                current = self.now()
                if not isinstance(current, datetime) or current.tzinfo is None:
                    raise ValueError
                report_id = _report_id(str(self.id_factory()))
                saved_at = current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            except (ValueError, TypeError, ResearchReportError):
                raise ResearchReportError("RESEARCH_REPORT_CONFIGURATION", 500) from None
            record = {"id": report_id, "title": title, "saved_at": saved_at, "byte_size": byte_size, "content_hash": digest, "payload": payload}
            result = await self._call("update_one", {
                "_id": owner, "schema_version": 1,
                "reports.content_hash": {"$ne": digest}, "reports.id": {"$ne": report_id},
                "$expr": {"$and": [
                    {"$lt": [{"$size": "$reports"}, self.max_reports]},
                    {"$lte": [{"$add": ["$used_bytes", byte_size]}, self.max_owner_bytes]},
                ]},
            }, {"$push": {"reports": record}, "$inc": {"used_bytes": byte_size}})
            if result.modified_count == 1:
                return {"report": _metadata(record), "replay": False}
            # A duplicate save may have won; always check it before reporting a
            # quota error so exact replay remains available at full capacity.
            bucket = await self._read(owner)
            if bucket is None:
                raise ResearchReportError("RESEARCH_REPORT_STORAGE_UNAVAILABLE", 503)
            duplicate = next((row for row in bucket["reports"] if row["content_hash"] == digest), None)
            if duplicate:
                if duplicate["payload"] != payload:
                    raise ResearchReportError("RESEARCH_REPORT_STORAGE_INVALID", 503)
                return {"report": _metadata(duplicate), "replay": True}
            if len(bucket["reports"]) >= self.max_reports or bucket["used_bytes"] + byte_size > self.max_owner_bytes:
                raise ResearchReportError("RESEARCH_REPORT_QUOTA", 413)
        raise ResearchReportError("RESEARCH_REPORT_CONFLICT", 409)

    async def list(self, owner) -> dict:
        bucket = await self._read(_owner(owner))
        return {"reports": [_metadata(row) for row in reversed(bucket["reports"])] if bucket else [],
                "used_bytes": bucket["used_bytes"] if bucket else 0, "limits": self.limits}

    async def get(self, owner, report_id) -> dict:
        owner, report_id = _owner(owner), _report_id(report_id)
        bucket = await self._read(owner)
        record = next((row for row in bucket["reports"] if row["id"] == report_id), None) if bucket else None
        if record is None:
            _not_found()
        return {"report": {**_metadata(record), "bundle": _decode(record["payload"])}}

    async def delete(self, owner, report_id) -> dict:
        owner, report_id = _owner(owner), _report_id(report_id)
        bucket = await self._read(owner)
        record = next((row for row in bucket["reports"] if row["id"] == report_id), None) if bucket else None
        if record is None:
            _not_found()
        result = await self._call("update_one", {
            "_id": owner, "schema_version": 1, "used_bytes": {"$gte": record["byte_size"]},
            "reports": {"$elemMatch": {"id": report_id, "content_hash": record["content_hash"], "byte_size": record["byte_size"]}},
        }, {"$pull": {"reports": {"id": report_id}}, "$inc": {"used_bytes": -record["byte_size"]}})
        if result.modified_count != 1:
            _not_found()
        return {"deleted": True}

"""Owner-fixed client for the private customer service, NOT the legacy gateway.

Only authenticated backend code supplies owner_id, base_url and the separate
FYND_COLLIDER_CUSTOMER_SECRET. No browser cookie, bearer token, owner claim or
caller URL is forwarded. Each request is signed with a fresh replay nonce; run
idempotency keys remain stable across explicit reconciliation. No automatic retry
or source fetch occurs here. Metadata reads do not start collection.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import math
import re
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx

from .client import (_COUNT_KEYS, _INPUT_KEYS, _RUN_STATES, _UNIT_STATES,
                     _coverage, _integer, _source_url, _timestamp, _validate_run)


OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
SECRET = re.compile(r"[A-Za-z0-9_-]{32,128}")
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
NONCE = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
HASH = re.compile(r"[a-f0-9]{64}")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
PREFIX = "/v1/customer"
SNAPSHOT_FIELDS = {"id", "runId", "unitId", "evidenceKind", "url", "title", "provider", "kind", "observedAt", "contentHash", "capturedAt", "snapshotHash"}


class CustomerColliderConfigurationError(ValueError):
    def __init__(self):
        super().__init__("Private customer service configuration is invalid.")


class CustomerColliderError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 502, uncertain: bool = False):
        self.code = code
        self.status_code = status_code
        self.uncertain = uncertain
        super().__init__("Private customer service request could not be verified.")


def _malformed() -> None:
    raise CustomerColliderError("UPSTREAM_RESPONSE")


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not UUID.fullmatch(value.lower()):
        raise CustomerColliderError("INVALID_REQUEST", status_code=400)
    return value.lower()


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _inspect(value: Any) -> None:
    nodes = 0

    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 150000 or depth > 20:
            _malformed()
        if type(item) is dict:
            for key, child in item.items():
                if not isinstance(key, str) or key in {"__proto__", "prototype", "constructor"}:
                    _malformed()
                key.encode("utf-8")
                visit(child, depth + 1)
        elif type(item) is list:
            if len(item) > 5000:
                _malformed()
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            item.encode("utf-8")
        elif type(item) is float and not math.isfinite(item):
            _malformed()
        elif item is not None and type(item) not in (int, float, bool):
            _malformed()

    visit(value)


def validate_customer_configuration(base_url: str, signing_key: str, owner_id: str) -> str:
    """Validate a fixed operator-only HTTPS origin, never an end-user URL."""
    try:
        if not isinstance(base_url, str) or not base_url or re.search(r"[\x00-\x20\x7f\\?#]", base_url):
            raise ValueError
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)
                or not isinstance(signing_key, str) or not SECRET.fullmatch(signing_key)
                or not isinstance(owner_id, str) or not OWNER.fullmatch(owner_id)):
            raise ValueError
        normalized = httpx.URL(base_url.rstrip("/") + "/")
        if normalized.host != parsed.hostname or normalized.username or normalized.password:
            raise ValueError
        return str(normalized)
    except (ValueError, TypeError, httpx.InvalidURL):
        raise CustomerColliderConfigurationError() from None


def validate_customer_input(value: Any) -> dict:
    """Bound user intent before signing; runtime still checks DNS/source policy.

    Do not normalize payloads here: the persisted runtime owns normalization and
    execution idempotency. A syntactically public URL is not permission to fetch.
    """
    def invalid():
        raise CustomerColliderError("INVALID_REQUEST", status_code=400)
    def text(item, maximum):
        if not isinstance(item, str) or not item.strip() or re.search(r"[\x00-\x1f\x7f-\x9f]", item):
            invalid()
        try:
            if len(item.encode("utf-16-le")) // 2 > maximum:
                invalid()
        except UnicodeError:
            invalid()
    try:
        if type(value) is not dict or not value or set(value) - _INPUT_KEYS:
            invalid()
        _inspect(value)
        if len(_json(value)) > 16384:
            invalid()
        urls, boards = value.get("urls", []), value.get("boards", [])
        if type(urls) is not list or len(urls) > 20 or type(boards) is not list or len(boards) > 3:
            invalid()
        for item in urls:
            text(item, 2048)
            if not _source_url(item):
                invalid()
            host = urlsplit(item).hostname
            if not host or "." not in host or host.endswith(".") or not re.fullmatch(r"[a-z0-9.-]+", host):
                invalid()
            if any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") for part in host.split(".")):
                invalid()
            if re.search(r"(^|\.)(localhost|local|internal|intranet|lan|home|test|invalid|example|onion)$", host) or re.search(r"(^|\.)(nip\.io|sslip\.io|localtest\.me)$", host):
                invalid()
            # Also reject WHATWG legacy numeric-address forms such as 127.1.
            if re.fullmatch(r"(?:[0-9]+|0x[a-f0-9]+)", host.rsplit(".", 1)[-1]):
                invalid()
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                invalid()
        seen = set()
        for board in boards:
            if type(board) is not dict or set(board) - {"provider", "board", "limit"} or board.get("provider") not in {"greenhouse", "lever", "lever-eu", "ashby"} or not isinstance(board.get("board"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", board["board"]):
                invalid()
            limit = board.get("limit", 10)
            identity = (board["provider"], board["board"])
            if type(limit) is not int or not 1 <= limit <= 20 or identity in seen:
                invalid()
            seen.add(identity)
        if "query" in value:
            text(value["query"], 400)
        if not urls and not boards and "query" not in value:
            invalid()
        if "pageLimit" in value and (type(value["pageLimit"]) is not int or not 1 <= value["pageLimit"] <= 20):
            invalid()
        if "followLinks" in value and type(value["followLinks"]) is not bool:
            invalid()
        if "maxDepth" in value and (value.get("followLinks") is not True or type(value["maxDepth"]) is not int or not 0 <= value["maxDepth"] <= 2):
            invalid()
        if "crawlMode" in value and value["crawlMode"] not in ("jobs", "web"):
            invalid()
        for name, maximum in (("providers", 4), ("querySlices", 3)):
            if name not in value:
                continue
            items = value[name]
            if "query" not in value or type(items) is not list or len(items) > maximum or (name == "providers" and not items):
                invalid()
            for item in items:
                text(item, 50 if name == "providers" else 400)
                if name == "providers" and not LABEL.fullmatch(item):
                    invalid()
            comparison = [item.strip() for item in items] + ([value["query"].strip()] if name == "querySlices" else [])
            if len(set(comparison)) != len(comparison):
                invalid()
        return value
    except Exception:
        invalid()


def _run_summary(value: Any) -> dict:
    expected = {"id", "input", "status", "createdAt", "updatedAt", "startedAt", "finishedAt", "cancelRequestedAt", "allocatedPages", "eventsDropped", "progress", "result"}
    if not isinstance(value, dict) or set(value) != expected or not isinstance(value["id"], str) or not UUID.fullmatch(value["id"]):
        _malformed()
    if value["status"] not in _RUN_STATES or not isinstance(value["input"], dict) or set(value["input"]) - _INPUT_KEYS:
        _malformed()
    if not all(_timestamp(value[key]) for key in ("createdAt", "updatedAt")) or not all(_timestamp(value[key], True) for key in ("startedAt", "finishedAt", "cancelRequestedAt")):
        _malformed()
    if not _integer(value["allocatedPages"], 20) or not _integer(value["eventsDropped"]):
        _malformed()
    progress, result = value["progress"], value["result"]
    if not isinstance(progress, dict) or set(progress) != _UNIT_STATES | {"total", "done"} or not all(_integer(number, 27) for number in progress.values()):
        _malformed()
    if sum(progress[state] for state in _UNIT_STATES) != progress["total"] or sum(progress[state] for state in ("completed", "partial", "failed", "uncertain")) != progress["done"]:
        _malformed()
    if not isinstance(result, dict) or set(result) != {"counts", "coverage", "selectionPriority", "incomplete"}:
        _malformed()
    if not isinstance(result["counts"], dict) or set(result["counts"]) != _COUNT_KEYS or not all(_integer(number) for number in result["counts"].values()) or not _coverage(result["coverage"]) or not isinstance(result["selectionPriority"], str):
        _malformed()
    if type(result["incomplete"]) is not bool or result["incomplete"] != (value["status"] != "completed" or progress["pending"] > 0 or progress["uncertain"] > 0):
        _malformed()
    return value


def _usage(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {"runs", "evidence", "requests", "queue", "scope"}:
        _malformed()
    def exact(item, names):
        if not isinstance(item, dict) or set(item) != set(names):
            _malformed()
    def numbers(item, names):
        if any(not _integer(item[name], 1_073_741_824) for name in names):
            _malformed()
    def limits(item, names):
        exact(item, names); numbers(item, names)
    def note(text):
        if not isinstance(text, str) or len(text) > 1000:
            _malformed()
    note(value["scope"])
    runs, evidence, requests, queue = (value[name] for name in ("runs", "evidence", "requests", "queue"))
    exact(runs, {"runs", "active", "queued", "paused", "allocatedPages", "storedBytes", "statuses", "limits", "storage"})
    numbers(runs, ("runs", "active", "queued", "paused", "allocatedPages", "storedBytes"))
    if not isinstance(runs["statuses"], dict) or set(runs["statuses"]) - _RUN_STATES:
        _malformed()
    numbers(runs["statuses"], runs["statuses"])
    if sum(runs["statuses"].values()) != runs["runs"]:
        _malformed()
    limits(runs["limits"], {"maxRuns", "maxPagesPerRun", "maxAllocatedPages", "maxBytesPerRun", "maxActive"}); note(runs["storage"])
    exact(evidence, {"runs", "snapshots", "storedBytes", "limits", "storage"})
    numbers(evidence, ("runs", "snapshots", "storedBytes"))
    limits(evidence["limits"], {"maxRunsPerOwner", "maxSnapshotsPerRun", "maxBytesPerRun", "maxBytesPerOwner"}); note(evidence["storage"])
    exact(requests, {"day", "reservedRequests", "remainingRequests", "limits"})
    numbers(requests, ("reservedRequests", "remainingRequests"))
    limits(requests["limits"], {"maxRequestsPerOwnerPerDay", "maxRequestsPerDay"})
    if not isinstance(requests["day"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requests["day"]) or not _timestamp(requests["day"] + "T00:00:00.000Z") or requests["remainingRequests"] != max(0, requests["limits"]["maxRequestsPerOwnerPerDay"] - requests["reservedRequests"]):
        _malformed()
    exact(queue, {"active", "queued", "closed", "limits"}); numbers(queue, ("active", "queued"))
    if queue["active"] > 1 or type(queue["closed"]) is not bool:
        _malformed()
    limits(queue["limits"], {"maxConcurrent", "maxQueued", "maxQueuedPerOwner"})
    return value


class CustomerColliderClient:
    def __init__(self, base_url: str, signing_key: str, *, owner_id: str,
                 timeout_seconds: float = 15.0, max_response_bytes: int = 8_388_608,
                 transport: httpx.AsyncBaseTransport | None = None,
                 now=time.time, nonce_factory=uuid.uuid4):
        origin = validate_customer_configuration(base_url, signing_key, owner_id)
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120
                or type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 8_388_608
                or not callable(now) or not callable(nonce_factory)):
            raise CustomerColliderConfigurationError()
        self._owner = owner_id
        self._signing_key = signing_key.encode("utf-8")
        self._timeout = timeout_seconds
        self._maximum = max_response_bytes
        self._now = now
        self._nonce_factory = nonce_factory
        self._closed = False
        self._http = httpx.AsyncClient(base_url=origin, timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False, trust_env=False, headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2), transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        if not self._closed:
            self._closed = True
            await self._http.aclose()

    def _headers(self, method: str, path: str, body: bytes, key: str | None) -> dict:
        try:
            current = self._now()
            if type(current) not in (int, float) or not math.isfinite(current) or not 0 <= current <= 253402300799:
                raise ValueError
            timestamp = str(math.floor(current))
            nonce = str(self._nonce_factory())
            if not NONCE.fullmatch(nonce):
                raise ValueError
            canonical = "\n".join(("LYNK-CUSTOMER-V1", method, path, self._owner, timestamp, nonce, key or "", hashlib.sha256(body).hexdigest()))
            signature = hmac.new(self._signing_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        except Exception:
            raise CustomerColliderError("INVALID_REQUEST", status_code=400) from None
        headers = {"x-lynk-owner": self._owner, "x-lynk-timestamp": timestamp,
                   "x-lynk-nonce": nonce, "x-lynk-signature": signature}
        if key is not None:
            headers["Idempotency-Key"] = key
        if method == "POST":
            headers["Content-Type"] = "application/json"
        return headers

    async def _request(self, method: str, path: str, *, body: bytes = b"", key: str | None = None, status: int = 200) -> dict:
        if self._closed:
            raise CustomerColliderError("CLIENT_CLOSED", status_code=503)
        headers = self._headers(method, path, body, key)

        async def exchange():
            async with self._http.stream(method, path, headers=headers, content=body) as response:
                if response.status_code != status:
                    code, code_status = {400: ("INVALID_REQUEST", 400), 401: ("UPSTREAM_AUTH", 503), 403: ("UPSTREAM_AUTH", 503),
                        404: ("UPSTREAM_NOT_FOUND", 404), 409: ("UPSTREAM_CONFLICT", 409), 413: ("UPSTREAM_LIMIT", 429),
                        429: ("UPSTREAM_CAPACITY", 429)}.get(response.status_code, ("UPSTREAM_FAILURE", 502))
                    raise CustomerColliderError(code, status_code=code_status,
                        uncertain=method == "POST" and (response.status_code < 400 or response.status_code >= 500))
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json" or response.headers.get("content-encoding", "identity").lower() != "identity":
                    _malformed()
                length = response.headers.get("content-length")
                if length is not None and (len(length) > 12 or not length.isascii() or not length.isdecimal() or int(length) > self._maximum):
                    raise CustomerColliderError("RESPONSE_LIMIT")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self._maximum:
                        raise CustomerColliderError("RESPONSE_LIMIT")
                    content.extend(chunk)
                try:
                    value = json.loads(content.decode("utf-8"), object_pairs_hook=_pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _inspect(value)
                    if not isinstance(value, dict):
                        _malformed()
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    _malformed()
                return value
        try:
            return await asyncio.wait_for(exchange(), self._timeout)
        except CustomerColliderError as failure:
            if method == "POST" and failure.code in {"UPSTREAM_RESPONSE", "RESPONSE_LIMIT"}:
                failure.uncertain = True
            raise
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise CustomerColliderError("UPSTREAM_TIMEOUT", status_code=504, uncertain=method == "POST") from None
        except (httpx.HTTPError, OSError):
            raise CustomerColliderError("UPSTREAM_UNAVAILABLE", status_code=503, uncertain=method == "POST") from None

    @staticmethod
    def _validated(callback, *, mutation=False):
        try:
            return callback()
        except Exception:
            raise CustomerColliderError("UPSTREAM_RESPONSE", uncertain=mutation) from None

    async def health(self):
        value = await self._request("GET", "/health")
        if set(value) != {"ok", "scope"} or value["ok"] is not True or not isinstance(value["scope"], str) or len(value["scope"]) > 1000:
            _malformed()
        return value

    async def list_runs(self):
        value = await self._request("GET", PREFIX + "/runs")
        def validate():
            if set(value) != {"runs"} or not isinstance(value["runs"], list) or len(value["runs"]) > 100:
                _malformed()
            runs = [_run_summary(run) for run in value["runs"]]
            if len({run["id"] for run in runs}) != len(runs):
                _malformed()
            return runs
        return self._validated(validate)

    async def submit_run(self, payload: dict, *, idempotency_key: str):
        if not isinstance(idempotency_key, str) or not OWNER.fullmatch(idempotency_key):
            raise CustomerColliderError("INVALID_REQUEST", status_code=400)
        validate_customer_input(payload)
        try:
            _inspect(payload)
            body = _json(payload)
            if len(body) > 16384:
                raise ValueError
        except Exception:
            raise CustomerColliderError("INVALID_REQUEST", status_code=400) from None
        value = await self._request("POST", PREFIX + "/runs", body=body, key=idempotency_key, status=202)
        def validate():
            if set(value) != {"replay", "run"} or type(value["replay"]) is not bool:
                _malformed()
            _validate_run(value["run"])
            return value
        return self._validated(validate, mutation=True)

    async def _one_run(self, run_id, action=None):
        run_id = _identifier(run_id)
        value = await self._request("POST" if action else "GET", PREFIX + "/runs/" + run_id + ("/" + action if action else ""), body=b"{}" if action else b"")
        def validate():
            if set(value) != {"run"}:
                _malformed()
            return _validate_run(value["run"], run_id)
        return self._validated(validate, mutation=bool(action))

    async def get_run(self, run_id):
        return await self._one_run(run_id)

    async def cancel_run(self, run_id):
        return await self._one_run(run_id, "cancel")

    async def resume_run(self, run_id):
        return await self._one_run(run_id, "resume")

    def _snapshot(self, value, run_id, snapshot_id=None, *, body=False):
        expected = SNAPSHOT_FIELDS | ({"markdown"} if body else set())
        if not isinstance(value, dict) or set(value) != expected or value["runId"] != run_id or _identifier(value["unitId"]) != value["unitId"] or not _source_url(value["url"]):
            _malformed()
        for name in ("id", "contentHash", "snapshotHash"):
            if not isinstance(value[name], str) or not HASH.fullmatch(value[name]):
                _malformed()
        if snapshot_id is not None and value["id"] != snapshot_id:
            _malformed()
        if not isinstance(value["title"], str) or len(value["title"]) > 500 or not all(isinstance(value[name], str) and LABEL.fullmatch(value[name]) for name in ("kind", "provider", "evidenceKind")):
            _malformed()
        if not _timestamp(value["capturedAt"]) or not _timestamp(value["observedAt"], True):
            _malformed()
        binding = ["run-evidence-binding-v1", self._owner, run_id, value["unitId"], value["evidenceKind"], value["url"]]
        if value["id"] != hashlib.sha256(_json(binding)).hexdigest():
            _malformed()
        if body:
            if not isinstance(value["markdown"], str) or len(value["markdown"]) > 60000:
                _malformed()
            if value["contentHash"] != hashlib.sha256(value["markdown"].encode("utf-8")).hexdigest():
                _malformed()
            # Match the immutable vault's explicit field order, not arbitrary
            # JSON response order. All values here are strings or null.
            ordered = {name: value[name] for name in ("id", "runId", "unitId", "evidenceKind", "url", "title", "markdown", "provider", "kind", "observedAt", "contentHash", "capturedAt")}
            if value["snapshotHash"] != hashlib.sha256(_json(ordered)).hexdigest():
                _malformed()
        return value

    async def list_snapshots(self, run_id):
        run_id = _identifier(run_id)
        value = await self._request("GET", PREFIX + "/runs/" + run_id + "/snapshots")
        def validate():
            if set(value) != {"snapshots"} or not isinstance(value["snapshots"], list) or len(value["snapshots"]) > 500:
                _malformed()
            rows = [self._snapshot(row, run_id) for row in value["snapshots"]]
            if len({row["id"] for row in rows}) != len(rows):
                _malformed()
            return rows
        return self._validated(validate)

    async def get_snapshot(self, run_id, snapshot_id):
        run_id = _identifier(run_id)
        if not isinstance(snapshot_id, str) or not HASH.fullmatch(snapshot_id):
            raise CustomerColliderError("INVALID_REQUEST", status_code=400)
        value = await self._request("GET", PREFIX + "/runs/" + run_id + "/snapshots/" + snapshot_id)
        def validate():
            if set(value) != {"snapshot"}:
                _malformed()
            return self._snapshot(value["snapshot"], run_id, snapshot_id, body=True)
        return self._validated(validate)

    async def usage(self):
        value = await self._request("GET", PREFIX + "/usage")
        def validate():
            if set(value) != {"usage"}:
                _malformed()
            return _usage(value["usage"])
        return self._validated(validate)

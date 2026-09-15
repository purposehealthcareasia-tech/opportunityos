"""Private, bounded HTTP adapter for the LYNK Collider gateway.

The application must authorize an owner-scoped run reference *before* calling
this client. The gateway is single-owner; this client is not a tenant boundary.
Only server configuration may supply base_url/token/idempotency_key. Never expose
them, or this class directly, to a browser. Extracted content remains untrusted.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_RUN_STATES = {"queued", "running", "paused", "cancel_requested", "completed", "partial", "failed", "cancelled"}
_UNIT_STATES = {"pending", "inflight", "completed", "partial", "failed", "uncertain"}
_INPUT_KEYS = {"urls", "query", "providers", "boards", "pageLimit", "followLinks", "maxDepth", "crawlMode", "querySlices"}
_COUNT_KEYS = {"savedPages", "savedJobs", "structuredRecords", "successfulEmptyBoards", "selectedPages", "attemptedPages", "discoveredUrls", "notFetched", "frontierOmitted", "linksSkipped", "omittedRecords", "truncatedRecords"}


class ColliderConfigurationError(ValueError):
    """Missing or unsafe server-only configuration; contains no config values."""


class ColliderError(RuntimeError):
    """Safe application-facing failure, never an upstream body or exception."""

    def __init__(self, code: str, *, status_code: int = 502, uncertain: bool = False):
        self.code = code
        self.status_code = status_code
        # True means a write may have reached the service. Reconcile using the
        # SAME persisted key/reference, not a newly generated submission key.
        self.uncertain = uncertain
        super().__init__("Collider request could not be verified (" + code + ").")


def _malformed() -> None:
    raise ColliderError("UPSTREAM_RESPONSE")


def _integer(value: Any, maximum: int = 10_000_000) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _timestamp(value: Any, nullable: bool = False) -> bool:
    if nullable and value is None:
        return True
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _array(value: Any, maximum: int) -> bool:
    return isinstance(value, list) and len(value) <= maximum


def _coverage(value: Any) -> bool:
    return isinstance(value, dict) and "percent" in value and "denominator" in value and value["percent"] is None and value["denominator"] is None


def _source_url(value: Any) -> bool:
    """A display-only URL check, not permission to fetch or proof of liveness."""
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value):
        return False
    try:
        url = urlsplit(value)
        return url.scheme == "https" and bool(url.hostname) and url.username is None and url.password is None and url.port in {None, 443}
    except ValueError:
        return False


def _document(value: dict[str, Any]) -> bool:
    if not _source_url(value.get("url")):
        return False
    for field in ("id", "contentHash", "previousContentHash"):
        if field in value and (not isinstance(value[field], str) or not re.fullmatch(r"[a-f0-9]{64}", value[field])):
            return False
    for field in ("title", "provider", "kind", "change", "company", "employerBoard", "location", "source", "evidenceKind"):
        if field in value and (not isinstance(value[field], str) or len(value[field]) > (2100 if field == "source" else 500)):
            return False
    for field in ("derivedJob", "structuredTruncated"):
        if field in value and type(value[field]) is not bool:
            return False
    return "expired" not in value or value["expired"] is None or type(value["expired"]) is bool


def _validate_run(value: Any, expected_id: str | None = None) -> dict[str, Any]:
    required = {"id", "input", "status", "createdAt", "updatedAt", "startedAt", "finishedAt", "cancelRequestedAt", "allocatedPages", "units", "events", "eventsDropped", "progress", "result"}
    if not isinstance(value, dict) or set(value) != required:
        _malformed()
    if not isinstance(value["id"], str) or not _UUID.fullmatch(value["id"]) or (expected_id is not None and value["id"] != expected_id):
        _malformed()
    if value["status"] not in _RUN_STATES or not isinstance(value["input"], dict) or set(value["input"]) - _INPUT_KEYS:
        _malformed()
    if not all(_timestamp(value[key]) for key in ("createdAt", "updatedAt")) or not all(_timestamp(value[key], True) for key in ("startedAt", "finishedAt", "cancelRequestedAt")):
        _malformed()
    if not _integer(value["allocatedPages"], 20) or not _integer(value["eventsDropped"]) or not _array(value["units"], 27) or not _array(value["events"], 100):
        _malformed()
    unit_ids: set[str] = set()
    counts: Counter[str] = Counter()
    for unit in value["units"]:
        required_unit = {"id", "kind", "input", "status", "startedAt", "finishedAt"}
        if not isinstance(unit, dict) or not required_unit <= set(unit) or set(unit) - required_unit - {"result", "error"}:
            _malformed()
        if not isinstance(unit["id"], str) or not _UUID.fullmatch(unit["id"]) or unit["id"] in unit_ids or unit["kind"] not in {"page", "board", "discovery"} or unit["status"] not in _UNIT_STATES:
            _malformed()
        if not isinstance(unit["input"], dict) or not all(_timestamp(unit[key], True) for key in ("startedAt", "finishedAt")) or ("result" in unit and not isinstance(unit["result"], dict)) or ("error" in unit and not isinstance(unit["error"], str)):
            _malformed()
        unit_ids.add(unit["id"])
        counts[unit["status"]] += 1
    for event in value["events"]:
        if not isinstance(event, dict) or not {"at", "type"} <= set(event) or set(event) - {"at", "type", "unitId"} or not _timestamp(event["at"]) or not isinstance(event["type"], str) or len(event["type"]) > 80 or ("unitId" in event and event["unitId"] not in unit_ids):
            _malformed()
    progress = value["progress"]
    if not isinstance(progress, dict) or set(progress) != _UNIT_STATES | {"total", "done"} or not all(_integer(n, 27) for n in progress.values()):
        _malformed()
    if progress["total"] != len(value["units"]) or any(progress[state] != counts[state] for state in _UNIT_STATES) or progress["done"] != sum(counts[state] for state in ("completed", "partial", "failed", "uncertain")):
        _malformed()
    result = value["result"]
    if not isinstance(result, dict) or set(result) != {"counts", "coverage", "selectionPriority", "incomplete", "pages", "jobs", "records", "errors", "warnings", "discovery", "searchSlices"}:
        _malformed()
    if not isinstance(result["counts"], dict) or set(result["counts"]) != _COUNT_KEYS or not all(_integer(n) for n in result["counts"].values()) or not _coverage(result["coverage"]) or not isinstance(result["selectionPriority"], str) or type(result["incomplete"]) is not bool:
        _malformed()
    for field, maximum in (("pages", 20), ("jobs", 460), ("records", 400), ("errors", 700), ("warnings", 700), ("searchSlices", 4)):
        if not _array(result[field], maximum) or any(not isinstance(item, dict) for item in result[field]):
            _malformed()
    if result["discovery"] is not None and not isinstance(result["discovery"], dict):
        _malformed()
    for field, count_field in (("pages", "savedPages"), ("jobs", "savedJobs"), ("records", "structuredRecords")):
        if len(result[field]) != result["counts"][count_field]:
            _malformed()
    if any(not _document(document) for field in ("pages", "jobs") for document in result[field]):
        _malformed()
    for record in result["records"]:
        if not _source_url(record.get("sourceUrl")) or not _array(record.get("types"), 8) or any(not isinstance(kind, str) for kind in record["types"]) or not isinstance(record.get("data"), dict) or ("truncated" in record and type(record["truncated"]) is not bool):
            _malformed()
    for item in result["errors"] + result["warnings"]:
        if item.get("unitId") not in unit_ids or not isinstance(item.get("code"), str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", item["code"]) or ("url" in item and not _source_url(item["url"])):
            _malformed()
    for item in result["searchSlices"]:
        if item.get("unitId") not in unit_ids or not isinstance(item.get("query"), str) or item.get("status") not in _UNIT_STATES or item.get("completeness") != "unknown" or not _array(item.get("results"), 10) or not _array(item.get("providers"), 4):
            _malformed()
        if item.get("returned") is not None and (not _integer(item["returned"], 10) or item["returned"] != len(item["results"])):
            _malformed()
        if any(not isinstance(row, dict) or not _source_url(row.get("url")) or not isinstance(row.get("title"), str) for row in item["results"]):
            _malformed()
    incomplete = value["status"] != "completed" or counts["pending"] > 0 or counts["uncertain"] > 0
    if result["incomplete"] != incomplete:
        _malformed()
    return value


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON keys")
        obj[key] = value
    return obj


def validate_configuration(base_url: str, token: str) -> str:
    """Validate server-only settings without opening or constructing a client.

    Returns the normalized fixed origin, including a trailing slash. The token
    is validated but never returned. Safe for repeated synchronous status calls.
    """
    try:
        if not isinstance(base_url, str) or base_url.strip() != base_url or re.search(r"[\x00-\x20\x7f]", base_url):
            raise ValueError
        url = urlsplit(base_url)
        port = url.port
        if url.scheme not in {"https", "http"} or not url.hostname or url.username is not None or url.password is not None or url.path not in {"", "/"} or url.query or url.fragment or (port is not None and not 1 <= port <= 65535):
            raise ValueError
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise ValueError
        normalized = httpx.URL(base_url.rstrip("/") + "/")
        # Guard parser disagreement or malformed network locations before any
        # credentials can be attached to a request.
        if normalized.host != url.hostname or normalized.username or normalized.password:
            raise ValueError
        return str(normalized)
    except (ValueError, TypeError, httpx.InvalidURL):
        raise ColliderConfigurationError("Collider requires a fixed server origin and valid private token.") from None


class ColliderClient:
    """A fixed-origin private client; no global runs, boards or evidence APIs."""

    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 15.0,
                 max_response_bytes: int = 2_097_152, transport: httpx.AsyncBaseTransport | None = None):
        # HTTP is supported only for the gateway's two accepted loopback hosts.
        # HTTPS must terminate at an operator-controlled private deployment. The
        # current gateway rejects public Host headers: a private reverse proxy
        # must explicitly rewrite Host to localhost; this client never spoofs it.
        normalized_url = validate_configuration(base_url, token)
        try:
            if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120:
                raise ValueError
            if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 8_388_608:
                raise ValueError
        except (ValueError, TypeError, httpx.InvalidURL):
            raise ColliderConfigurationError("Collider requires bounded time and response limits.") from None
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._http = httpx.AsyncClient(
            base_url=normalized_url, headers={"Authorization": "Bearer " + token, "Accept": "application/json", "Accept-Encoding": "identity"},
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5), transport=transport,
        )

    async def __aenter__(self) -> ColliderClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, *, body: bytes | None = None,
                       idempotency_key: str | None = None, expected_status: int = 200) -> dict[str, Any]:
        async def exchange() -> dict[str, Any]:
            headers = {}
            if body is not None:
                headers["Content-Type"] = "application/json"
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key
            async with self._http.stream(method, path, headers=headers, content=body) as response:
                if response.status_code != expected_status:
                    code, status = {
                        400: ("INVALID_REQUEST", 400), 401: ("UPSTREAM_AUTH", 503), 403: ("UPSTREAM_AUTH", 503),
                        404: ("UPSTREAM_NOT_FOUND", 404), 409: ("IDEMPOTENCY_CONFLICT", 409),
                        413: ("UPSTREAM_LIMIT", 429), 429: ("UPSTREAM_CAPACITY", 429),
                    }.get(response.status_code, ("UPSTREAM_FAILURE", 502))
                    # Never parse or expose upstream error text, headers or URLs.
                    raise ColliderError(code, status_code=status, uncertain=method == "POST" and (response.status_code < 400 or response.status_code >= 500))
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media_type != "application/json" or response.headers.get("content-encoding", "identity").lower() != "identity":
                    _malformed()
                length = response.headers.get("content-length")
                if length is not None and (len(length) > 12 or not length.isascii() or not length.isdecimal() or int(length) > self._max_response_bytes):
                    raise ColliderError("RESPONSE_LIMIT")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self._max_response_bytes:
                        raise ColliderError("RESPONSE_LIMIT")
                    content.extend(chunk)
                try:
                    payload = json.loads(content.decode("utf-8"), object_pairs_hook=_json_object,
                                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError, RecursionError):
                    _malformed()
                if not isinstance(payload, dict):
                    _malformed()
                return payload
        try:
            return await asyncio.wait_for(exchange(), self._timeout_seconds)
        except ColliderError as exc:
            if method == "POST" and exc.code in {"UPSTREAM_RESPONSE", "RESPONSE_LIMIT"}:
                exc.uncertain = True
            raise
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise ColliderError("UPSTREAM_TIMEOUT", status_code=504, uncertain=method == "POST") from None
        except httpx.HTTPError:
            raise ColliderError("UPSTREAM_UNAVAILABLE", status_code=503, uncertain=method == "POST") from None

    async def health(self) -> dict[str, Any]:
        """Gateway liveness only, never scraping-provider readiness."""
        result = await self._request("GET", "/health")
        if set(result) != {"ok", "scope"} or result["ok"] is not True or not isinstance(result["scope"], str):
            _malformed()
        return result

    async def capabilities(self) -> dict[str, Any]:
        result = await self._request("GET", "/v1/capabilities")
        if set(result) != {"providers", "publicJobBoards", "features", "limits", "coverage", "scope"} or not _array(result["providers"], 20) or not isinstance(result["limits"], dict) or not _coverage(result["coverage"]) or not isinstance(result["scope"], str):
            _malformed()
        for field in ("publicJobBoards", "features"):
            if not _array(result[field], 100) or any(not isinstance(item, str) or len(item) > 200 for item in result[field]):
                _malformed()
        for provider in result["providers"]:
            if not isinstance(provider, dict) or not isinstance(provider.get("id"), str) or type(provider.get("configured")) is not bool:
                _malformed()
        return result

    async def submit_run(self, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        """Use a key persisted by the backend *before* first submission.

        No automatic retry is made. After an uncertain outcome, the application
        must retry the same authorized payload/key, never allocate a fresh key.
        """
        if not isinstance(idempotency_key, str) or not _KEY.fullmatch(idempotency_key) or not isinstance(payload, dict) or not payload or set(payload) - _INPUT_KEYS:
            raise ColliderError("INVALID_REQUEST", status_code=400)
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise ColliderError("INVALID_REQUEST", status_code=400) from None
        if len(body) > 16_384:
            raise ColliderError("INVALID_REQUEST", status_code=400)
        result = await self._request("POST", "/v1/runs", body=body, idempotency_key=idempotency_key, expected_status=202)
        try:
            if set(result) != {"replay", "run"} or type(result["replay"]) is not bool:
                _malformed()
            _validate_run(result["run"])
        except (ColliderError, TypeError, KeyError):
            raise ColliderError("UPSTREAM_RESPONSE", uncertain=True) from None
        return result

    @staticmethod
    def _run_id(run_id: str) -> str:
        if not isinstance(run_id, str) or not _UUID.fullmatch(run_id.lower()):
            raise ColliderError("INVALID_REQUEST", status_code=400)
        return run_id.lower()

    async def _one_run(self, run_id: str, action: str | None = None) -> dict[str, Any]:
        run_id = self._run_id(run_id)
        method = "POST" if action else "GET"
        result = await self._request(method, "/v1/runs/" + run_id + ("/" + action if action else ""), body=b"{}" if action else None)
        try:
            if set(result) != {"run"}:
                _malformed()
            return _validate_run(result["run"], run_id)
        except (ColliderError, TypeError, KeyError):
            raise ColliderError("UPSTREAM_RESPONSE", uncertain=bool(action)) from None

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._one_run(run_id)

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return await self._one_run(run_id, "cancel")

    async def resume_run(self, run_id: str) -> dict[str, Any]:
        """Resumes paused pending work; never promises to retry failed units."""
        return await self._one_run(run_id, "resume")

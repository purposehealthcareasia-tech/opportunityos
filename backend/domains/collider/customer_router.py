"""Authenticated, default-off Fynd bridge to the private customer service.

No startup work, provider registration, URL fetches or account-identity claims
come from this module. The operator-controlled service checks current source
policy and owns durable execution budgets, run ownership and immutable evidence.
The legacy idempotency middleware MUST exclude this exact prefix before cache
lookup: its cache is not this route's authenticated execution idempotency layer.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from collections import OrderedDict
from contextlib import contextmanager

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from core.config import settings
from core.deps import get_current_user

from .customer_client import (OWNER, CustomerColliderClient, CustomerColliderConfigurationError,
                              CustomerColliderError, _identifier, validate_customer_configuration,
                              validate_customer_input)
from .report import ColliderReportError, assemble_report


PREFIX = "/api/v1/collider/scans"
MAX_BODY_BYTES = 16 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOTS = 500
REQUEST_TIMEOUT_SECONDS = 30.0
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
SAFE_MESSAGE = "The account scan request could not be completed."
SCOPE = "Bounded, account-scoped collection. Availability means configured, not provider readiness or internet coverage."


def _failure(code, status, *, uncertain=False):
    return JSONResponse({"detail": {"code": code, "message": SAFE_MESSAGE, "uncertain": bool(uncertain)}},
                        status_code=status, headers=PRIVATE_HEADERS)


class _PrivateScanRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def protected(request: Request):
            request.state.collider_mutation_sent = False
            try:
                response = await asyncio.wait_for(original(request), timeout=REQUEST_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                return _failure("SCAN_TIMEOUT", 504, uncertain=request.state.collider_mutation_sent)
            except CustomerColliderError as error:
                return _failure(error.code, error.status_code, uncertain=error.uncertain)
            except ColliderReportError as error:
                return _failure(error.code, error.status_code)
            except CustomerColliderConfigurationError:
                return _failure("SCAN_NOT_CONFIGURED", 503)
            except HTTPException as error:
                code = {401: "SCAN_UNAUTHORIZED", 403: "SCAN_FORBIDDEN", 404: "SCAN_NOT_FOUND",
                        413: "SCAN_TOO_LARGE", 429: "SCAN_RATE_LIMITED"}.get(error.status_code, "SCAN_REQUEST_FAILED")
                return _failure(code, error.status_code)
            except RequestValidationError:
                return _failure("INVALID_REQUEST", 400)
            except Exception:
                # No raw upstream, source, auth or configuration details escape.
                return _failure("SCAN_UNAVAILABLE", 503, uncertain=request.state.collider_mutation_sent)
            response.headers.update(PRIVATE_HEADERS)
            return response

        return protected


class _OwnerRateLimiter:
    """Process-local abuse guard only; durable request quotas live upstream."""
    def __init__(self, *, requests=60, window_seconds=60.0, max_owners=1000, clock=time.monotonic):
        self.requests, self.window_seconds = requests, window_seconds
        self.max_owners, self.clock = max_owners, clock
        self.windows = OrderedDict()

    def consume(self, owner):
        current = self.clock()
        while self.windows and current - next(iter(self.windows.values()))[0] >= self.window_seconds:
            self.windows.popitem(last=False)
        entry = self.windows.get(owner)
        if entry is None:
            if len(self.windows) >= self.max_owners:
                raise CustomerColliderError("SCAN_RATE_LIMITED", status_code=429)
            self.windows[owner] = (current, 1)
        elif entry[1] >= self.requests:
            raise CustomerColliderError("SCAN_RATE_LIMITED", status_code=429)
        else:
            self.windows[owner] = (entry[0], entry[1] + 1)


class _ReportAdmission:
    """At most four hydrations per worker and one per authenticated account.

    Claiming is synchronous on this worker's event loop, with no waiting queue or
    idle-owner registry. This limits concurrent bounded report allocations, not
    distributed account quotas. The claim spans hydration and report assembly.
    """
    def __init__(self):
        self.owners = set()

    @contextmanager
    def hold(self, owner):
        if owner in self.owners or len(self.owners) >= 4:
            raise CustomerColliderError("SCAN_REPORT_CAPACITY", status_code=429)
        self.owners.add(owner)
        try:
            yield
        finally:
            self.owners.remove(owner)


_limiter = _OwnerRateLimiter()
_report_admission = _ReportAdmission()
router = APIRouter(prefix=PREFIX, tags=["collider-scans"], route_class=_PrivateScanRoute)


def _access(request, user, *, mutation=False):
    if type(user) is not dict or user.get("_auth_mode") not in ("cookie", "bearer_ci") or not isinstance(user.get("id"), str) or not OWNER.fullmatch(user["id"]):
        raise CustomerColliderError("SCAN_UNAUTHORIZED", status_code=401)
    if user.get("deletion_pending_at") is not None:
        raise CustomerColliderError("SCAN_ACCOUNT_UNAVAILABLE", status_code=403)
    if request.query_params:
        raise CustomerColliderError("INVALID_REQUEST", status_code=400)
    if mutation and user["_auth_mode"] == "cookie":
        cookie, header = request.cookies.get(settings.CSRF_COOKIE_NAME), request.headers.get(settings.CSRF_HEADER_NAME)
        if not cookie or not header or len(cookie) > 512 or len(header) > 512 or not hmac.compare_digest(cookie.encode("utf-8"), header.encode("utf-8")):
            raise CustomerColliderError("SCAN_CSRF", status_code=403)
    _limiter.consume(user["id"])
    return user["id"]


def _configuration(owner):
    if os.environ.get("FYND_COLLIDER_CUSTOMER_ENABLED") != "true":
        return None, "disabled"
    base_url = os.environ.get("FYND_COLLIDER_CUSTOMER_BASE_URL", "")
    secret = os.environ.get("FYND_COLLIDER_CUSTOMER_SECRET", "")
    try:
        validate_customer_configuration(base_url, secret, owner)
    except CustomerColliderConfigurationError:
        return None, "configuration_required"
    return (base_url, secret), None


def _client(owner):
    configured, _ = _configuration(owner)
    if configured is None:
        raise CustomerColliderError("SCAN_NOT_CONFIGURED", status_code=503)
    return CustomerColliderClient(*configured, owner_id=owner, timeout_seconds=10.0)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


async def _body(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json" or request.headers.get("content-encoding", "identity").lower() != "identity":
        raise CustomerColliderError("SCAN_CONTENT_TYPE", status_code=415)
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal():
            raise CustomerColliderError("INVALID_REQUEST", status_code=400)
        if len(declared) > 10 or int(declared) > MAX_BODY_BYTES:
            raise CustomerColliderError("SCAN_TOO_LARGE", status_code=413)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            raise CustomerColliderError("SCAN_TOO_LARGE", status_code=413)
        raw.extend(chunk)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(value) is not dict:
            raise ValueError
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise CustomerColliderError("INVALID_REQUEST", status_code=400) from None


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))


@router.get("/capabilities")
async def capabilities(request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user)
    configured, reason = _configuration(owner)
    return {"available": configured is not None, "reason": reason,
            "limits": {"max_pages_per_run": 20, "max_snapshot_bytes": MAX_SNAPSHOT_BYTES, "max_snapshots": MAX_SNAPSHOTS},
            "scope": SCOPE}


@router.get("")
async def list_scans(request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user)
    async with _client(owner) as client:
        return {"runs": await client.list_runs()}


@router.post("", status_code=202)
async def start_scan(request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user, mutation=True)
    value = await _body(request)
    if set(value) != {"input", "confirm_storage"} or value["confirm_storage"] is not True:
        raise CustomerColliderError("INVALID_REQUEST", status_code=400)
    payload = validate_customer_input(value["input"])
    keys = request.headers.getlist("idempotency-key")
    if len(keys) != 1 or not OWNER.fullmatch(keys[0]):
        raise CustomerColliderError("INVALID_REQUEST", status_code=400)
    async with _client(owner) as client:
        request.state.collider_mutation_sent = True
        return await client.submit_run(payload, idempotency_key=keys[0])


@router.get("/{run_id}")
async def get_scan(run_id: str, request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user)
    run_id = _identifier(run_id)
    async with _client(owner) as client:
        return {"run": await client.get_run(run_id)}


async def _action(run_id, request, user, action):
    owner = _access(request, user, mutation=True)
    run_id = _identifier(run_id)
    if await _body(request) != {}:
        raise CustomerColliderError("INVALID_REQUEST", status_code=400)
    # Generic Fynd mutation wrappers may add a key to every POST. Validate but
    # ignore that optional header: this action targets an existing owner/run,
    # not a new keyed execution. Never forward it to the private service.
    keys = request.headers.getlist("idempotency-key")
    if len(keys) > 1 or (keys and not OWNER.fullmatch(keys[0])):
        raise CustomerColliderError("INVALID_REQUEST", status_code=400)
    async with _client(owner) as client:
        request.state.collider_mutation_sent = True
        return {"run": await getattr(client, action)(run_id)}


@router.post("/{run_id}/cancel")
async def cancel_scan(run_id: str, request: Request, user: dict = Depends(get_current_user)):
    return await _action(run_id, request, user, "cancel_run")


@router.post("/{run_id}/resume")
async def resume_scan(run_id: str, request: Request, user: dict = Depends(get_current_user)):
    return await _action(run_id, request, user, "resume_run")


@router.get("/{run_id}/report")
async def scan_report(run_id: str, request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user)
    run_id = _identifier(run_id)
    with _report_admission.hold(owner):
        async with _client(owner) as client:
            run = await client.get_run(run_id)
            # Terminal runs cannot resume or append new work in the runtime.
            # Do not race a changing run summary against later snapshot reads.
            if run["status"] not in {"completed", "partial", "failed", "cancelled"}:
                raise CustomerColliderError("SCAN_IN_PROGRESS", status_code=409)
            metadata = await client.list_snapshots(run_id)
            if len(metadata) > MAX_SNAPSHOTS:
                raise ColliderReportError("REPORT_TOO_LARGE", 413)
            retained_bytes = _bytes(run) + _bytes(metadata)
            if retained_bytes > MAX_SNAPSHOT_BYTES:
                raise ColliderReportError("REPORT_TOO_LARGE", 413)
            snapshots = []
            # Deliberately sequential: no unbounded fan-out or parallel allocation.
            for row in metadata:
                snapshot = await client.get_snapshot(run_id, row["id"])
                retained_bytes += _bytes(snapshot)
                if retained_bytes > MAX_SNAPSHOT_BYTES:
                    raise ColliderReportError("REPORT_TOO_LARGE", 413)
                snapshots.append(snapshot)
        bundle = assemble_report(run, metadata, snapshots, expected_run_id=run_id)
        if _bytes(bundle) > MAX_SNAPSHOT_BYTES:
            raise ColliderReportError("REPORT_TOO_LARGE", 413)
        return bundle

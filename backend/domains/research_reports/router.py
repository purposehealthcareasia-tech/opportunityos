"""Authenticated storage of explicitly confirmed, inert research snapshots.

This router never collects URLs, submits applications, interprets source text,
or uses a client-supplied account identifier. The legacy idempotency middleware
must exclude this exact route prefix: this service deduplicates by owner/content.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from core.config import settings
from core.db import get_db
from core.deps import get_current_user

from .service import OWNER_PATTERN, ResearchReportError, ResearchReportService


MAX_BODY_BYTES = 8 * 1024 * 1024 + 64 * 1024
REQUEST_TIMEOUT_SECONDS = 10.0
SAFE_MESSAGE = "Research report storage request could not be completed."
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _failure(code: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": {"code": code, "message": SAFE_MESSAGE}},
                        status_code=status, headers=PRIVATE_HEADERS)


class _PrivateReportRoute(APIRoute):
    """Apply the deadline and private error policy to dependencies as well."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def protected(request: Request):
            try:
                response = await asyncio.wait_for(original(request), timeout=REQUEST_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                return _failure("RESEARCH_REPORT_TIMEOUT", 504)
            except ResearchReportError as failure:
                return _failure(failure.code, failure.status)
            except HTTPException as failure:
                code = {401: "RESEARCH_REPORT_UNAUTHORIZED", 403: "RESEARCH_REPORT_FORBIDDEN",
                        404: "RESEARCH_REPORT_NOT_FOUND", 413: "RESEARCH_REPORT_TOO_LARGE",
                        429: "RESEARCH_REPORT_RATE_LIMITED"}.get(failure.status_code, "RESEARCH_REPORT_REQUEST_FAILED")
                return _failure(code, failure.status_code)
            except RequestValidationError:
                return _failure("RESEARCH_REPORT_INVALID", 400)
            except Exception:
                # No upstream details, report content, or account data returned
                # or logged. Cancellation from shutdown/client work propagates.
                return _failure("RESEARCH_REPORT_STORAGE_UNAVAILABLE", 503)
            response.headers.update(PRIVATE_HEADERS)
            return response

        return protected


class _OwnerRateLimiter:
    """Modest process-local abuse guard, not a distributed billing/quota system.

    A fixed monotonic window and at most 1000 entries bound memory. Full active
    capacity fails closed, rather than evicting active owners to reset counters.
    Database byte/count quotas remain the cross-process source of truth.
    """

    def __init__(self, *, requests=60, window_seconds=60.0, max_owners=1000, clock=None):
        self.requests = requests
        self.window_seconds = window_seconds
        self.max_owners = max_owners
        self.clock = clock or time.monotonic
        self.windows = OrderedDict()

    def consume(self, owner: str) -> None:
        current = self.clock()
        while self.windows and current - next(iter(self.windows.values()))[0] >= self.window_seconds:
            self.windows.popitem(last=False)
        entry = self.windows.get(owner)
        if entry is None:
            if len(self.windows) >= self.max_owners:
                raise ResearchReportError("RESEARCH_REPORT_RATE_LIMITED", 429)
            self.windows[owner] = (current, 1)
        elif entry[1] >= self.requests:
            raise ResearchReportError("RESEARCH_REPORT_RATE_LIMITED", 429)
        else:
            self.windows[owner] = (entry[0], entry[1] + 1)


_limiter = _OwnerRateLimiter()
router = APIRouter(prefix="/api/v1/research/reports", tags=["research-reports"], route_class=_PrivateReportRoute)


def _access(request: Request, user: dict, *, mutation: bool = False) -> str:
    if not isinstance(user, dict) or user.get("_auth_mode") not in ("cookie", "bearer_ci"):
        raise ResearchReportError("RESEARCH_REPORT_UNAUTHORIZED", 401)
    owner = user.get("id")
    if not isinstance(owner, str) or not OWNER_PATTERN.fullmatch(owner):
        raise ResearchReportError("RESEARCH_REPORT_UNAUTHORIZED", 401)
    if user.get("deletion_pending_at") is not None:
        raise ResearchReportError("RESEARCH_REPORT_ACCOUNT_UNAVAILABLE", 403)
    if request.query_params:
        raise ResearchReportError("RESEARCH_REPORT_INVALID", 400)
    if mutation and user["_auth_mode"] == "cookie":
        # Do not trust an Authorization header to bypass cookie CSRF checks.
        # Auth mode comes only from the existing authenticated dependency.
        cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
        header = request.headers.get(settings.CSRF_HEADER_NAME)
        if not cookie or not header or len(cookie) > 512 or len(header) > 512 or not hmac.compare_digest(cookie.encode("utf-8"), header.encode("utf-8")):
            raise ResearchReportError("RESEARCH_REPORT_CSRF", 403)
    _limiter.consume(owner)
    return owner


def _service() -> ResearchReportService:
    return ResearchReportService(get_db()["research_report_buckets"])


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError


async def _confirmed_bundle(request: Request) -> dict:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ResearchReportError("RESEARCH_REPORT_CONTENT_TYPE", 415)
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal():
            raise ResearchReportError("RESEARCH_REPORT_INVALID", 400)
        # Compare length before converting to avoid pathological huge integers.
        if len(declared) > 10 or int(declared) > MAX_BODY_BYTES:
            raise ResearchReportError("RESEARCH_REPORT_TOO_LARGE", 413)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise ResearchReportError("RESEARCH_REPORT_TOO_LARGE", 413)
        body.extend(chunk)
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise ResearchReportError("RESEARCH_REPORT_INVALID", 400) from None
    if type(value) is not dict or set(value) != {"bundle", "confirm_storage"} or value["confirm_storage"] is not True:
        raise ResearchReportError("RESEARCH_REPORT_INVALID", 400)
    return value["bundle"]


@router.get("")
async def list_reports(request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user)
    return await _service().list(owner)


@router.post("")
async def save_report(request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user, mutation=True)
    bundle = await _confirmed_bundle(request)
    return await _service().save(owner, bundle)


@router.get("/{report_id}")
async def get_report(report_id: str, request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user)
    return await _service().get(owner, report_id)


@router.delete("/{report_id}")
async def delete_report(report_id: str, request: Request, user: dict = Depends(get_current_user)):
    owner = _access(request, user, mutation=True)
    return await _service().delete(owner, report_id)

"""Isolated ASGI tests: stub authentication/database, no sockets or live Mongo.

Run with unittest discovery, not the application's pytest autouse fixtures.
FastAPI and httpx are the existing backend runtime test dependencies.
"""
import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request

from test_research_reports_service import FakeCollection, bundle


PREFIX = "/api/v1/research/reports"


class ResearchReportRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.collection = FakeCollection()
        self.auth_calls = 0
        self.auth_delay = 0
        self.database_lookups = 0

        async def get_current_user(request: Request):
            self.auth_calls += 1
            if self.auth_delay:
                await asyncio.sleep(self.auth_delay)
            owner = request.headers.get("x-test-owner")
            if not owner:
                raise HTTPException(401, detail="PRIVATE_AUTHENTICATION_TRACE")
            user = {"id": owner, "_auth_mode": request.headers.get("x-test-mode", "cookie")}
            if request.headers.get("x-test-deleting"):
                user["deletion_pending_at"] = "2026-09-13T00:00:00Z"
            return user

        def get_db():
            self.database_lookups += 1
            return {"research_report_buckets": self.collection}

        core = types.ModuleType("core"); core.__path__ = []
        config = types.ModuleType("core.config")
        config.settings = types.SimpleNamespace(CSRF_COOKIE_NAME="test-csrf", CSRF_HEADER_NAME="X-Test-CSRF")
        database = types.ModuleType("core.db"); database.get_db = get_db
        deps = types.ModuleType("core.deps"); deps.get_current_user = get_current_user
        name = "domains.research_reports._isolated_router_test"
        source = Path(__file__).resolve().parents[1] / "domains" / "research_reports" / "router.py"
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        # Temporary module substitution affects this isolated router only. It
        # neither imports nor mutates the production app's configuration/auth.
        with patch.dict(sys.modules, {"core": core, "core.config": config, "core.db": database,
                                     "core.deps": deps, name: module}):
            spec.loader.exec_module(module)
        self.router_module = module
        app = FastAPI()
        app.include_router(module.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://asgi.test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def request(self, method, path=PREFIX, *, owner="user:A", mode="cookie", csrf=True, headers=None, **kwargs):
        request_headers = {"x-test-mode": mode}
        if owner is not None:
            request_headers["x-test-owner"] = owner
        if csrf:
            request_headers.update({"cookie": "test-csrf=synthetic-csrf", "X-Test-CSRF": "synthetic-csrf"})
        request_headers.update(headers or {})
        response = await self.client.request(method, path, headers=request_headers, **kwargs)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("pragma"), "no-cache")
        return response

    async def save(self, *, owner="user:A", value=None, **kwargs):
        return await self.request("POST", owner=owner, json={"bundle": value or bundle(), "confirm_storage": True}, **kwargs)

    async def test_exact_save_list_get_delete_envelopes_and_private_headers(self):
        saved = await self.save()
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(set(saved.json()), {"report", "replay"})
        metadata = saved.json()["report"]
        self.assertEqual(set(metadata), {"id", "title", "saved_at", "byte_size"})
        listing = await self.request("GET")
        self.assertEqual(listing.json(), {"reports": [metadata], "used_bytes": metadata["byte_size"],
            "limits": {"max_reports": 20, "max_report_bytes": 8388608, "max_total_bytes": 10485760}})
        loaded = await self.request("GET", f"{PREFIX}/{metadata['id']}")
        self.assertEqual(loaded.json(), {"report": {**metadata, "bundle": bundle()}})
        deleted = await self.request("DELETE", f"{PREFIX}/{metadata['id']}")
        self.assertEqual(deleted.json(), {"deleted": True})
        self.assertEqual((await self.request("GET")).json()["used_bytes"], 0)
        self.assertEqual(self.auth_calls, 5)

    async def test_authentication_required_on_every_route_without_exposing_dependency_details(self):
        for method, path in [("GET", PREFIX), ("POST", PREFIX), ("GET", f"{PREFIX}/{uuid4()}"), ("DELETE", f"{PREFIX}/{uuid4()}")]:
            response = await self.request(method, path, owner=None)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("PRIVATE_AUTHENTICATION_TRACE", response.text)
        self.assertEqual(self.auth_calls, 4)
        self.assertEqual(self.database_lookups, 0)
        self.assertEqual(self.collection.calls, [])

    async def test_cookie_csrf_cannot_be_bypassed_with_arbitrary_bearer_header(self):
        saved = (await self.save()).json()["report"]
        self.collection.calls.clear()
        for method, path in [("POST", PREFIX), ("DELETE", f"{PREFIX}/{saved['id']}")]:
            for headers in [{}, {"Authorization": "Bearer irrelevant-header"},
                            {"cookie": "test-csrf=cookie-value", "X-Test-CSRF": "wrong-value"},
                            {"X-Test-CSRF": "header-without-cookie"}]:
                response = await self.request(method, path, csrf=False, headers=headers,
                                              json={"bundle": bundle(), "confirm_storage": True})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["detail"]["code"], "RESEARCH_REPORT_CSRF")
        self.assertEqual(self.collection.calls, [])
        # Cookie-authenticated reads don't mutate storage and need no CSRF.
        self.assertEqual((await self.request("GET", csrf=False)).status_code, 200)

    async def test_only_trusted_bearer_ci_auth_mode_skips_csrf(self):
        saved = await self.save(mode="bearer_ci", csrf=False)
        self.assertEqual(saved.status_code, 200)
        deleted = await self.request("DELETE", f"{PREFIX}/{saved.json()['report']['id']}", mode="bearer_ci", csrf=False)
        self.assertEqual(deleted.status_code, 200)
        for mode in ("bearer", "anonymous", ""):
            self.assertEqual((await self.request("GET", mode=mode)).status_code, 401)

    async def test_pending_account_deletion_blocks_all_routes(self):
        for method, path in [("GET", PREFIX), ("POST", PREFIX), ("GET", f"{PREFIX}/{uuid4()}"), ("DELETE", f"{PREFIX}/{uuid4()}")]:
            response = await self.request(method, path, headers={"x-test-deleting": "yes"})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.database_lookups, 0)

    async def test_query_parameters_and_client_owner_claims_are_rejected(self):
        for method in ("GET", "POST", "DELETE"):
            path = PREFIX if method != "DELETE" else f"{PREFIX}/{uuid4()}"
            response = await self.request(method, path + "?owner=user:B", json={"bundle": bundle(), "confirm_storage": True})
            self.assertEqual(response.status_code, 400)
        for extra in ("owner", "owner_id", "user_id", "id", "saved_at"):
            response = await self.request("POST", json={"bundle": bundle(), "confirm_storage": True, extra: "untrusted"})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database_lookups, 0)

    async def test_explicit_boolean_confirmation_is_mandatory(self):
        variants = [{"bundle": bundle()}, {"bundle": bundle(), "confirm_storage": False},
                    {"bundle": bundle(), "confirm_storage": 1}, {"bundle": bundle(), "confirm_storage": "true"},
                    {"confirm_storage": True}, [], None]
        for value in variants:
            response = await self.request("POST", content=json.dumps(value), headers={"content-type": "application/json"})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database_lookups, 0)

    async def test_malformed_utf8_duplicate_keys_and_non_json_content_are_rejected(self):
        variants = [b"\xff", b"{bad}", b'{"bundle":{},"confirm_storage":true,"confirm_storage":true}',
                    b'{"bundle":{"manifest":1,"manifest":2},"confirm_storage":true}',
                    b'{"bundle":NaN,"confirm_storage":true}']
        for content in variants:
            response = await self.request("POST", content=content, headers={"content-type": "application/json"})
            self.assertEqual(response.status_code, 400)
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "application/jsonp", ""):
            response = await self.request("POST", content=b"{}", headers={"content-type": content_type})
            self.assertEqual(response.status_code, 415)
        self.assertEqual(self.database_lookups, 0)

    async def test_oversized_declared_body_rejected_before_streaming_and_database(self):
        streamed = []

        async def body():
            streamed.append(True)
            yield b"{}"

        response = await self.request("POST", content=body(), headers={"content-type": "application/json",
            "content-length": str(self.router_module.MAX_BODY_BYTES + 1)})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(streamed, [])
        self.assertEqual(self.database_lookups, 0)

    async def test_streamed_body_cap_applies_without_or_with_forged_content_length(self):
        self.router_module.MAX_BODY_BYTES = 512
        for declared in (None, "1"):
            chunks = []

            async def body():
                for index in range(5):
                    chunks.append(index)
                    yield b" " * 300

            headers = {"content-type": "application/json"}
            if declared is not None:
                headers["content-length"] = declared
            response = await self.request("POST", content=body(), headers=headers)
            self.assertEqual(response.status_code, 413)
            self.assertEqual(chunks, [0, 1])
        self.assertEqual(self.database_lookups, 0)

    async def test_missing_and_foreign_valid_ids_are_indistinguishable(self):
        saved = (await self.save()).json()["report"]
        for method in ("GET", "DELETE"):
            foreign = await self.request(method, f"{PREFIX}/{saved['id']}", owner="user:B")
            missing = await self.request(method, f"{PREFIX}/{uuid4()}", owner="user:B")
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), missing.json())
        self.assertEqual((await self.request("GET", owner="user:B")).json()["reports"], [])

    async def test_client_idempotency_header_never_skips_ownership_or_payload_validation(self):
        headers = {"Idempotency-Key": "same-client-key"}
        first = await self.save(headers=headers)
        replay = await self.save(headers=headers)
        different = await self.save(value=bundle(title="Another snapshot"), headers=headers)
        foreign = await self.save(owner="user:B", headers=headers)
        self.assertTrue(replay.json()["replay"])
        self.assertEqual(replay.json()["report"], first.json()["report"])
        self.assertNotEqual(different.json()["report"]["id"], first.json()["report"]["id"])
        self.assertNotEqual(foreign.json()["report"]["id"], first.json()["report"]["id"])
        malformed = await self.request("POST", json={"bundle": bundle(), "confirm_storage": False}, headers=headers)
        self.assertEqual(malformed.status_code, 400)

    async def test_auth_body_and_database_deadlines_return_private_generic_errors(self):
        self.router_module.REQUEST_TIMEOUT_SECONDS = 0.01
        self.auth_delay = 0.05
        response = await self.request("GET")
        self.assertEqual(response.status_code, 504)
        self.auth_delay = 0

        async def slow_body():
            yield b"{"
            await asyncio.sleep(0.05)
            yield b"}"

        response = await self.request("POST", content=slow_body(), headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 504)
        original_find = self.collection.find_one

        async def slow_find(query):
            await asyncio.sleep(0.05)
            return await original_find(query)

        self.collection.find_one = slow_find
        response = await self.request("GET")
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["detail"]["code"], "RESEARCH_REPORT_TIMEOUT")

    async def test_database_errors_do_not_escape_and_committed_save_retry_replays(self):
        self.collection.fail_after_append = True
        response = await self.save()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SYNTHETIC_INTERNAL_DATABASE_TRACE", response.text)
        retry = await self.save()
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["replay"])

    async def test_rate_limits_are_owner_scoped_and_memory_bounded_with_expiry(self):
        current = [0.0]
        limiter = self.router_module._OwnerRateLimiter(requests=2, max_owners=2, window_seconds=60, clock=lambda: current[0])
        self.router_module._limiter = limiter
        self.assertEqual((await self.request("GET")).status_code, 200)
        self.assertEqual((await self.request("GET")).status_code, 200)
        self.assertEqual((await self.request("GET")).status_code, 429)
        self.assertEqual((await self.request("GET", owner="user:B")).status_code, 200)
        self.assertEqual((await self.request("GET", owner="user:C")).status_code, 429)
        self.assertEqual(len(limiter.windows), 2)
        current[0] = 60.0
        self.assertEqual((await self.request("GET", owner="user:C")).status_code, 200)
        self.assertEqual(len(limiter.windows), 1)


if __name__ == "__main__":
    unittest.main()

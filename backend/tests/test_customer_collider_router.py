"""Isolated ASGI + real customer-client protocol tests; no sockets or providers."""
import asyncio
import copy
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException, Request

from domains.collider.customer_client import CustomerColliderClient
from test_customer_collider_client import (INPUT, KEY, NONCE, NOW, OWNER, RUN, STAMP, UNIT,
                                          canonical, run_fixture, snapshot_fixture, summary_fixture)


PREFIX = "/api/v1/collider/scans"
OTHER_RUN = "42345678-1234-4234-8234-123456789abc"


class CustomerRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.auth_calls = 0
        self.auth_delay = 0
        self.upstream_calls = []
        self.instances = []
        self.handler = self.dispatch
        self.run = run_fixture()
        self.snapshots = []
        self.keys = {}
        self.environment = patch.dict(os.environ, {
            "FYND_COLLIDER_CUSTOMER_ENABLED": "true",
            "FYND_COLLIDER_CUSTOMER_BASE_URL": "https://private-customer.example.org",
            "FYND_COLLIDER_CUSTOMER_SECRET": KEY,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

        async def get_current_user(request: Request):
            self.auth_calls += 1
            if self.auth_delay:
                await asyncio.sleep(self.auth_delay)
            owner = request.headers.get("x-test-owner")
            if owner is None:
                raise HTTPException(401, "PRIVATE_AUTH_TRACE")
            result = {"id": owner, "_auth_mode": request.headers.get("x-test-mode", "cookie")}
            if request.headers.get("x-test-deleting"):
                result["deletion_pending_at"] = NOW
            return result

        core = types.ModuleType("core"); core.__path__ = []
        config = types.ModuleType("core.config")
        config.settings = types.SimpleNamespace(CSRF_COOKIE_NAME="test-csrf", CSRF_HEADER_NAME="X-Test-CSRF")
        deps = types.ModuleType("core.deps"); deps.get_current_user = get_current_user
        name = "domains.collider._isolated_customer_router_test"
        source = Path(__file__).resolve().parents[1] / "domains" / "collider" / "customer_router.py"
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"core": core, "core.config": config, "core.deps": deps, name: module}):
            spec.loader.exec_module(module)
        self.module = module

        async def transport(request):
            self.upstream_calls.append(request)
            response = self.handler(request)
            return await response if hasattr(response, "__await__") else response

        def factory(base, key, **kwargs):
            value = CustomerColliderClient(base, key, **kwargs, transport=httpx.MockTransport(transport),
                                           now=lambda: STAMP, nonce_factory=lambda: NONCE)
            self.instances.append(value)
            return value

        module.CustomerColliderClient = factory
        app = FastAPI()
        app.include_router(module.router)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://asgi.test")
        self.addAsyncCleanup(self.http.aclose)

    def dispatch(self, request):
        path = request.url.path
        owner = request.headers["x-lynk-owner"]
        if path == "/v1/customer/runs":
            if request.method == "GET":
                return httpx.Response(200, json={"runs": [summary_fixture()] if owner == OWNER else []})
            key = (owner, request.headers["idempotency-key"])
            prior = self.keys.get(key)
            if prior is not None and prior != request.content:
                return httpx.Response(409, json={"private": "PRIVATE_UPSTREAM_TRACE"})
            self.keys[key] = request.content
            return httpx.Response(202, json={"replay": prior is not None, "run": self.run})
        if owner != OWNER or OTHER_RUN in path:
            return httpx.Response(404, json={"private": "PRIVATE_UPSTREAM_TRACE"})
        if path.endswith("/snapshots"):
            return httpx.Response(200, json={"snapshots": [{k: v for k, v in row.items() if k != "markdown"} for row in self.snapshots]})
        if "/snapshots/" in path:
            found = next((row for row in self.snapshots if row["id"] == path.rsplit("/", 1)[-1]), None)
            return httpx.Response(200, json={"snapshot": found})
        return httpx.Response(200, json={"run": self.run})

    async def request(self, method, suffix="", *, owner=OWNER, mode="cookie", csrf=True, headers=None, **kwargs):
        supplied = {"x-test-mode": mode}
        if owner is not None:
            supplied["x-test-owner"] = owner
        if csrf:
            supplied.update({"cookie": "test-csrf=synthetic-csrf", "X-Test-CSRF": "synthetic-csrf"})
        supplied.update(headers or {})
        response = await self.http.request(method, PREFIX + suffix, headers=supplied, **kwargs)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("pragma"), "no-cache")
        self.assertNotIn(KEY, response.text)
        self.assertNotIn("PRIVATE_AUTH_TRACE", response.text)
        self.assertNotIn("PRIVATE_UPSTREAM_TRACE", response.text)
        return response

    async def start(self, *, value=None, key="stable-execution-key", **kwargs):
        return await self.request("POST", headers={"Idempotency-Key": key},
                                  json=value if value is not None else {"input": INPUT, "confirm_storage": True}, **kwargs)

    def completed_evidence(self):
        self.snapshots = [snapshot_fixture()]
        self.run.update(status="completed", startedAt=NOW, finishedAt=NOW)
        self.run["units"][0].update(status="completed", startedAt=NOW, finishedAt=NOW)
        self.run["progress"].update(pending=0, done=1, completed=1)
        result = self.run["result"]
        result["incomplete"] = False
        result["counts"].update(savedPages=1, attemptedPages=1, notFetched=0)
        snap = self.snapshots[0]
        result["pages"] = [{"url": snap["url"], "title": snap["title"], "provider": snap["provider"], "kind": "page",
                            "evidenceRetention": "retained", "evidenceSnapshotId": snap["id"], "contentHash": snap["contentHash"]}]

    async def test_capabilities_is_auth_required_local_configuration_only_and_default_off(self):
        for enabled in (None, "false", "True", "1", ""):
            if enabled is None:
                os.environ.pop("FYND_COLLIDER_CUSTOMER_ENABLED", None)
            else:
                os.environ["FYND_COLLIDER_CUSTOMER_ENABLED"] = enabled
            response = await self.request("GET", "/capabilities")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["available"])
            self.assertEqual(response.json()["reason"], "disabled")
            self.assertEqual((await self.request("GET")).status_code, 503)
        os.environ["FYND_COLLIDER_CUSTOMER_ENABLED"] = "true"
        for name, value in (("FYND_COLLIDER_CUSTOMER_SECRET", "bad"), ("FYND_COLLIDER_CUSTOMER_BASE_URL", "http://unsafe.example.org")):
            with patch.dict(os.environ, {name: value}):
                response = await self.request("GET", "/capabilities")
                self.assertEqual(response.json()["reason"], "configuration_required")
                self.assertFalse(response.json()["available"])
                self.assertEqual((await self.start()).status_code, 503)
        available = await self.request("GET", "/capabilities")
        self.assertTrue(available.json()["available"])
        self.assertIsNone(available.json()["reason"])
        self.assertIn("not provider readiness", available.json()["scope"])
        self.assertEqual(available.json()["limits"]["max_snapshots"], 500)
        self.assertNotIn("private-customer", available.text)
        self.assertEqual(self.upstream_calls, [])
        self.assertEqual(self.instances, [])

    async def test_all_routes_require_trusted_auth_and_reject_deleting_accounts_before_transport(self):
        routes = [("GET", "/capabilities"), ("GET", ""), ("POST", ""), ("GET", "/" + RUN),
                  ("POST", f"/{RUN}/cancel"), ("POST", f"/{RUN}/resume"), ("GET", f"/{RUN}/report")]
        for method, path in routes:
            self.assertEqual((await self.request(method, path, owner=None)).status_code, 401)
            self.assertEqual((await self.request(method, path, headers={"x-test-deleting": "yes"})).status_code, 403)
        for owner, mode in (("has space", "cookie"), ("valid-owner", "bearer"), ("valid-owner", "anonymous"), ("", "cookie")):
            self.assertEqual((await self.request("GET", owner=owner, mode=mode)).status_code, 401)
        self.assertEqual(self.upstream_calls, [])

    async def test_real_client_envelopes_owner_signing_fresh_instances_and_close(self):
        self.assertEqual((await self.request("GET")).json(), {"runs": [summary_fixture()]})
        started = await self.start()
        self.assertEqual(started.status_code, 202)
        self.assertEqual(started.json(), {"run": self.run, "replay": False})
        self.assertTrue((await self.start()).json()["replay"])
        self.assertEqual((await self.request("GET", "/" + RUN)).json(), {"run": self.run})
        for action in ("cancel", "resume"):
            response = await self.request("POST", f"/{RUN}/{action}", json={})
            self.assertEqual(response.json(), {"run": self.run})
        self.assertEqual(len(self.instances), 6)
        self.assertTrue(all(client._closed for client in self.instances))
        self.assertTrue(all(request.headers["x-lynk-owner"] == OWNER for request in self.upstream_calls))
        self.assertTrue(all("authorization" not in request.headers and "cookie" not in request.headers for request in self.upstream_calls))
        self.assertTrue(all(request.url.host == "private-customer.example.org" for request in self.upstream_calls))
        self.assertTrue(all("x-test-owner" not in request.headers for request in self.upstream_calls))

    async def test_cookie_csrf_cannot_be_bypassed_by_bearer_headers_but_ci_mode_is_supported(self):
        for action in ("", f"/{RUN}/cancel", f"/{RUN}/resume"):
            for headers in ({}, {"Authorization": "Bearer irrelevant"}, {"cookie": "test-csrf=one", "X-Test-CSRF": "two"}):
                response = await self.request("POST", action, csrf=False, headers=headers, json={})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["detail"]["code"], "SCAN_CSRF")
        self.assertEqual(self.upstream_calls, [])
        self.assertEqual((await self.start(mode="bearer_ci", csrf=False)).status_code, 202)
        self.assertEqual((await self.request("POST", f"/{RUN}/cancel", mode="bearer_ci", csrf=False, json={})).status_code, 200)
        self.assertEqual((await self.request("GET", csrf=False)).status_code, 200)

    async def test_query_params_owner_claims_confirmation_and_idempotency_keys_fail_before_transport(self):
        for method, path in (("GET", ""), ("GET", "/capabilities"), ("POST", ""), ("GET", "/" + RUN), ("POST", f"/{RUN}/cancel"), ("GET", f"/{RUN}/report")):
            self.assertEqual((await self.request(method, path + "?owner=B", json={})).status_code, 400)
        values = [{"input": INPUT}, {"input": INPUT, "confirm_storage": False}, {"input": INPUT, "confirm_storage": 1},
                  {"input": INPUT, "confirm_storage": "true"}, {"input": INPUT, "confirm_storage": True, "owner": "B"},
                  {"input": {**INPUT, "ownerId": "B"}, "confirm_storage": True}]
        for value in values:
            self.assertEqual((await self.start(value=value)).status_code, 400)
        for key in ("", "space key", "x" * 129, "bad/key"):
            self.assertEqual((await self.start(key=key)).status_code, 400)
        self.assertEqual((await self.request("POST", json={"input": INPUT, "confirm_storage": True})).status_code, 400)
        for body in ({"input": INPUT}, {"owner": "B"}, [], None):
            self.assertEqual((await self.request("POST", f"/{RUN}/cancel", content=json.dumps(body), headers={"content-type": "application/json"})).status_code, 400)
        self.assertEqual((await self.request("POST", f"/{RUN}/resume", json={}, headers={"Idempotency-Key": "bad/key"})).status_code, 400)
        self.assertEqual(self.upstream_calls, [])

    async def test_action_wrapper_keys_are_accepted_but_not_forwarded_or_signed(self):
        for action in ("cancel", "resume"):
            for key in ("generic-wrapper-key", "another-wrapper-key"):
                response = await self.request("POST", f"/{RUN}/{action}", json={}, headers={"Idempotency-Key": key})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"run": self.run})
                outgoing = self.upstream_calls[-1]
                self.assertNotIn("idempotency-key", outgoing.headers)
                self.assertEqual(outgoing.content, b"{}")
                canonical_message = "\n".join(["LYNK-CUSTOMER-V1", "POST", f"/v1/customer/runs/{RUN}/{action}",
                    OWNER, str(STAMP), NONCE, "", hashlib.sha256(b"{}").hexdigest()])
                self.assertEqual(outgoing.headers["x-lynk-signature"],
                    hmac.new(KEY.encode(), canonical_message.encode(), hashlib.sha256).hexdigest())
        self.assertEqual(len(self.upstream_calls), 4)
        self.assertEqual(self.keys, {}, "Existing-run actions must not create keyed executions")

    async def test_duplicate_or_malformed_action_keys_and_duplicate_start_keys_are_rejected(self):
        for suffix in (f"/{RUN}/cancel", f"/{RUN}/resume"):
            for key in ("", "contains space", "bad/key", "x" * 129):
                response = await self.request("POST", suffix, json={}, headers={"Idempotency-Key": key})
                self.assertEqual(response.status_code, 400)
        for suffix in ("", f"/{RUN}/cancel", f"/{RUN}/resume"):
            response = await self.http.post(PREFIX + suffix,
                headers=[("x-test-owner", OWNER), ("x-test-mode", "bearer_ci"),
                         ("Idempotency-Key", "same-valid-key"), ("idempotency-key", "same-valid-key")],
                json={"input": INPUT, "confirm_storage": True} if not suffix else {})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            self.assertEqual(response.json()["detail"]["code"], "INVALID_REQUEST")
        self.assertEqual(self.upstream_calls, [])
        self.assertEqual(self.instances, [])

    async def test_invalid_identifiers_and_nonpublic_or_malformed_inputs_make_no_signed_requests(self):
        for identifier in ("not-a-uuid", "_", "012345", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaaX"):
            self.assertEqual((await self.request("GET", "/" + identifier)).status_code, 400)
            self.assertEqual((await self.request("POST", f"/{identifier}/cancel", json={})).status_code, 400)
        urls = ["http://example.org", "https://localhost", "https://10.0.0.1", "https://127.1", "https://0x7f.1",
                "https://[::1]", "https://example.org:8443", "https://name:password@example.org", "https://example.org\\@evil.com",
                "https://host.internal", "https://a.nip.io", "https://example.org.", "https://example.org/has space"]
        for url in urls:
            self.assertEqual((await self.start(value={"input": {"urls": [url]}, "confirm_storage": True})).status_code, 400)
        for value in ({"query": ""}, {"query": "x\nsecret"}, {"query": "🌍" * 201}, {"urls": INPUT["urls"], "pageLimit": True},
                      {"urls": INPUT["urls"], "pageLimit": 21}, {"urls": INPUT["urls"], "maxDepth": 1},
                      {"urls": INPUT["urls"], "followLinks": 1}, {"query": "x", "querySlices": [" x "]},
                      {"query": "x", "providers": []}, {"boards": [{"provider": "private", "board": "x"}]},
                      {"boards": [{"provider": "lever", "board": "x", "limit": 21}]}):
            self.assertEqual((await self.start(value={"input": value, "confirm_storage": True})).status_code, 400)
        self.assertEqual(self.upstream_calls, [])

    async def test_duplicate_keys_invalid_utf8_nonfinite_deep_json_and_nonjson_bodies_are_rejected(self):
        bodies = [b"\xff", b'{"input":{},"input":{},"confirm_storage":true}', b'{"input":{"query":"a","query":"b"},"confirm_storage":true}',
                  b'{"input":NaN,"confirm_storage":true}', b'{"input":{"query":"\\ud800"},"confirm_storage":true}', b"[0]",
                  b'{"input":' + b"[" * 1200 + b"0" + b"]" * 1200 + b',"confirm_storage":true}']
        for body in bodies:
            response = await self.request("POST", content=body, headers={"content-type": "application/json", "Idempotency-Key": "stable"})
            self.assertEqual(response.status_code, 400)
        for headers in ({"content-type": "text/plain"}, {"content-type": "application/json", "content-encoding": "gzip"}):
            self.assertEqual((await self.request("POST", content=b"{}", headers=headers)).status_code, 415)
        self.assertEqual(self.upstream_calls, [])

    async def test_declared_and_streamed_body_limits_apply_before_upstream_effects(self):
        streamed = []
        async def content():
            streamed.append(True)
            yield b"{}"
        response = await self.request("POST", content=content(), headers={"content-type": "application/json", "content-length": str(self.module.MAX_BODY_BYTES + 1)})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(streamed, [])
        self.module.MAX_BODY_BYTES = 100
        for declared in (None, "1"):
            streamed.clear()
            async def chunks():
                for number in range(5):
                    streamed.append(number)
                    yield b" " * 60
            headers = {"content-type": "application/json"}
            if declared:
                headers["content-length"] = declared
            self.assertEqual((await self.request("POST", content=chunks(), headers=headers)).status_code, 413)
            self.assertEqual(streamed, [0, 1])
        self.assertEqual(self.upstream_calls, [])

    async def test_owner_isolation_missing_foreign_and_persisted_key_conflict(self):
        self.assertEqual((await self.start()).status_code, 202)
        conflict = await self.start(value={"input": {"query": "different"}, "confirm_storage": True})
        self.assertEqual(conflict.status_code, 409)
        self.assertFalse(conflict.json()["detail"]["uncertain"])
        self.assertFalse((await self.start(owner="account:B")).json()["replay"])
        self.assertEqual((await self.request("GET", owner="account:B")).json(), {"runs": []})
        foreign = await self.request("GET", "/" + RUN, owner="account:B")
        absent = await self.request("GET", "/" + OTHER_RUN, owner="account:B")
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), absent.json())

    async def test_report_is_exact_inert_bundle_from_bound_snapshots_and_never_recrawls(self):
        self.completed_evidence()
        first = await self.request("GET", f"/{RUN}/report")
        second = await self.request("GET", f"/{RUN}/report")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(set(first.json()), {"manifest", "files"})
        evidence = json.loads(first.json()["files"]["evidence.jsonl"].strip())
        self.assertEqual(evidence["content"], self.snapshots[0]["markdown"])
        self.assertEqual(evidence["retainedSnapshot"]["id"], self.snapshots[0]["id"])
        self.assertEqual(first.json()["manifest"]["runSummary"]["id"], RUN)
        self.assertEqual([request.url.path for request in self.upstream_calls[:3]], [f"/v1/customer/runs/{RUN}",
                          f"/v1/customer/runs/{RUN}/snapshots", f"/v1/customer/runs/{RUN}/snapshots/{self.snapshots[0]['id']}"])
        self.assertTrue(all(request.method == "GET" for request in self.upstream_calls))
        self.assertTrue(all(client._closed for client in self.instances))

    async def test_report_allows_only_terminal_runs_before_any_snapshot_read(self):
        for status in ("queued", "running", "paused", "cancel_requested"):
            self.run["status"] = status
            before = len(self.upstream_calls)
            response = await self.request("GET", f"/{RUN}/report")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "SCAN_IN_PROGRESS")
            self.assertFalse(response.json()["detail"]["uncertain"])
            self.assertEqual(len(self.upstream_calls), before + 1)
            self.assertEqual(self.upstream_calls[-1].url.path, f"/v1/customer/runs/{RUN}")
            self.assertEqual(self.module._report_admission.owners, set())
        self.completed_evidence()
        for status in ("completed", "partial", "failed", "cancelled"):
            self.run["status"] = status
            self.run["result"]["incomplete"] = status != "completed"
            response = await self.request("GET", f"/{RUN}/report")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["manifest"]["runSummary"]["status"], status)
        self.assertEqual(self.module._report_admission.owners, set())

    async def test_report_admission_is_one_per_owner_four_per_worker_and_fail_fast(self):
        reached = asyncio.Event()
        release = asyncio.Event()
        async def blocked(request):
            if len(self.upstream_calls) == 4:
                reached.set()
            await release.wait()
            return httpx.Response(404, json={"private": "PRIVATE_UPSTREAM_TRACE"})
        self.handler = blocked
        owners = [OWNER, "account:B", "account:C", "account:D"]
        tasks = [asyncio.create_task(self.request("GET", f"/{RUN}/report", owner=owner)) for owner in owners]
        try:
            await asyncio.wait_for(reached.wait(), 1)
            self.assertEqual(self.module._report_admission.owners, set(owners))
            for owner in (OWNER, "account:E"):
                response = await self.request("GET", f"/{RUN}/report", owner=owner)
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.json()["detail"]["code"], "SCAN_REPORT_CAPACITY")
            self.assertEqual(len(self.instances), 4)
            self.assertEqual(len(self.upstream_calls), 4)
            # A saturated report hydrator does not block local capability reads.
            self.assertEqual((await self.request("GET", "/capabilities", owner="account:E")).status_code, 200)
        finally:
            release.set()
            responses = await asyncio.gather(*tasks)
        self.assertTrue(all(response.status_code == 404 for response in responses))
        self.assertEqual(self.module._report_admission.owners, set())
        self.assertTrue(all(client._closed for client in self.instances))
        self.handler = self.dispatch
        self.completed_evidence()
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 200)

    async def test_report_admission_releases_on_request_cancellation_and_timeout(self):
        self.completed_evidence()
        reached = asyncio.Event()
        async def blocked(request):
            if "/snapshots/" not in request.url.path:
                return self.dispatch(request)
            reached.set()
            await asyncio.Event().wait()
        self.handler = blocked
        pending = asyncio.create_task(self.request("GET", f"/{RUN}/report"))
        await asyncio.wait_for(reached.wait(), 1)
        self.assertEqual(self.module._report_admission.owners, {OWNER})
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(self.module._report_admission.owners, set())
        self.assertTrue(self.instances[-1]._closed)
        self.module.REQUEST_TIMEOUT_SECONDS = 0.01
        response = await self.request("GET", f"/{RUN}/report")
        self.assertEqual(response.status_code, 504)
        self.assertFalse(response.json()["detail"]["uncertain"])
        self.assertEqual(self.module._report_admission.owners, set())
        self.assertTrue(self.instances[-1]._closed)
        self.handler = self.dispatch
        self.module.REQUEST_TIMEOUT_SECONDS = 30
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 200)
        self.assertEqual(self.module._report_admission.owners, set())

    async def test_report_owner_admission_applies_below_the_global_limit(self):
        reached = asyncio.Event()
        async def blocked(request):
            reached.set()
            await asyncio.Event().wait()
        self.handler = blocked
        pending = asyncio.create_task(self.request("GET", f"/{RUN}/report"))
        try:
            await asyncio.wait_for(reached.wait(), 1)
            response = await self.request("GET", f"/{RUN}/report")
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()["detail"]["code"], "SCAN_REPORT_CAPACITY")
            self.assertEqual(len(self.instances), 1)
            self.assertEqual(len(self.upstream_calls), 1)
            self.assertEqual(self.module._report_admission.owners, {OWNER})
        finally:
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
        self.assertEqual(self.module._report_admission.owners, set())

    async def test_report_admission_releases_if_configuration_or_assembler_fails(self):
        with patch.dict(os.environ, {"FYND_COLLIDER_CUSTOMER_ENABLED": "false"}):
            self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 503)
        self.assertEqual(self.module._report_admission.owners, set())
        self.assertEqual(self.instances, [])
        self.completed_evidence()
        with patch.object(self.module, "assemble_report", side_effect=RuntimeError("PRIVATE_UPSTREAM_TRACE")):
            self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 503)
        self.assertEqual(self.module._report_admission.owners, set())
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 200)

    async def test_report_count_and_cumulative_bytes_fail_without_fetching_rest(self):
        self.completed_evidence()
        self.module.MAX_SNAPSHOTS = 0
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 413)
        self.assertEqual(len(self.upstream_calls), 2)
        self.module.MAX_SNAPSHOTS = 500
        second = copy.deepcopy(self.snapshots[0])
        second["unitId"] = "52345678-1234-4234-8234-123456789abc"
        second["id"] = hashlib.sha256(canonical(["run-evidence-binding-v1", OWNER, RUN, second["unitId"], second["evidenceKind"], second["url"]])).hexdigest()
        second["snapshotHash"] = hashlib.sha256(canonical({key: value for key, value in second.items() if key != "snapshotHash"})).hexdigest()
        self.snapshots.append(second)
        meta = [{key: value for key, value in row.items() if key != "markdown"} for row in self.snapshots]
        self.module.MAX_SNAPSHOT_BYTES = len(canonical(self.run)) + len(canonical(meta)) + len(canonical(self.snapshots[0])) - 1
        self.upstream_calls.clear()
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 413)
        self.assertEqual(len(self.upstream_calls), 3)
        self.assertNotIn(second["id"], str(self.upstream_calls[-1].url))

    async def test_report_wrong_owner_hash_or_run_never_reaches_assembler(self):
        self.completed_evidence()
        self.snapshots = [snapshot_fixture(owner="another-account")]
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 502)
        self.assertEqual(len(self.upstream_calls), 2)
        self.completed_evidence()
        self.snapshots[0]["markdown"] += " changed"
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 502)
        self.run["id"] = OTHER_RUN
        before = len(self.upstream_calls)
        self.assertEqual((await self.request("GET", f"/{RUN}/report")).status_code, 502)
        self.assertEqual(len(self.upstream_calls), before + 1)

    async def test_deadlines_cover_auth_body_and_upstream_with_honest_mutation_uncertainty(self):
        self.module.REQUEST_TIMEOUT_SECONDS = 0.01
        self.auth_delay = 0.1
        response = await self.request("GET", "/capabilities")
        self.assertEqual(response.status_code, 504)
        self.assertFalse(response.json()["detail"]["uncertain"])
        self.auth_delay = 0
        async def body():
            yield b"{"
            await asyncio.sleep(0.1)
        response = await self.request("POST", content=body(), headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 504)
        self.assertFalse(response.json()["detail"]["uncertain"])
        self.assertEqual(self.upstream_calls, [])
        async def slow_upstream(request):
            await asyncio.sleep(0.1)
            return self.dispatch(request)
        self.handler = slow_upstream
        response = await self.start()
        self.assertEqual(response.status_code, 504)
        self.assertTrue(response.json()["detail"]["uncertain"])
        self.assertEqual(len(self.upstream_calls), 1)
        self.assertTrue(self.instances[0]._closed)
        self.assertFalse((await self.request("GET")).json()["detail"]["uncertain"])

    async def test_upstream_failures_are_sanitized_and_never_retried(self):
        self.handler = lambda _: httpx.Response(500, json={"secret": "PRIVATE_UPSTREAM_TRACE"})
        response = await self.start()
        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.json()["detail"]["uncertain"])
        self.assertEqual(len(self.upstream_calls), 1)
        self.assertTrue(self.instances[0]._closed)

    async def test_rate_limit_is_per_owner_bounded_and_expiring(self):
        now = [0.0]
        self.module._limiter = self.module._OwnerRateLimiter(requests=2, max_owners=2, clock=lambda: now[0])
        for _ in range(2):
            self.assertEqual((await self.request("GET", "/capabilities")).status_code, 200)
        self.assertEqual((await self.request("GET", "/capabilities")).status_code, 429)
        self.assertEqual((await self.request("GET", "/capabilities", owner="B")).status_code, 200)
        self.assertEqual((await self.request("GET", "/capabilities", owner="C")).status_code, 429)
        self.assertEqual(len(self.module._limiter.windows), 2)
        now[0] = 60.0
        self.assertEqual((await self.request("GET", "/capabilities", owner="C")).status_code, 200)
        self.assertEqual(len(self.module._limiter.windows), 1)


if __name__ == "__main__":
    unittest.main()

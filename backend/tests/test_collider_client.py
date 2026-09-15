"""Synthetic contract tests only: MockTransport, no sockets or live scraping."""

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from domains.collider.client import ColliderClient, ColliderConfigurationError, ColliderError, validate_configuration


TOKEN = "SYNTHETIC_GATEWAY_TOKEN_NEVER_REAL_123456"
RUN_ID = "12345678-1234-4234-8234-123456789abc"
UNIT_ID = "22345678-1234-4234-8234-123456789abc"
NOW = "2026-09-08T12:00:00.000Z"
INPUT = {"urls": ["https://example.org/jobs"], "pageLimit": 1}


def run_fixture(status="queued"):
    unit_status = "completed" if status == "completed" else "pending"
    return {
        "id": RUN_ID, "input": {**INPUT, "boards": [], "followLinks": False},
        "status": status, "createdAt": NOW, "updatedAt": NOW,
        "startedAt": NOW if status == "completed" else None,
        "finishedAt": NOW if status in {"completed", "cancelled"} else None,
        "cancelRequestedAt": NOW if status == "cancelled" else None,
        "allocatedPages": 1, "eventsDropped": 0,
        "units": [{"id": UNIT_ID, "kind": "page", "input": {"url": INPUT["urls"][0], "depth": 0, "origin": "https://example.org"}, "status": unit_status, "startedAt": None, "finishedAt": None}],
        "events": [{"at": NOW, "type": "queued"}],
        "progress": {"total": 1, "done": int(status == "completed"), "pending": int(status != "completed"), "inflight": 0, "completed": int(status == "completed"), "partial": 0, "failed": 0, "uncertain": 0},
        "result": {
            "counts": {"savedPages": 0, "savedJobs": 0, "structuredRecords": 0, "successfulEmptyBoards": 0, "selectedPages": 1, "attemptedPages": int(status == "completed"), "discoveredUrls": 1, "notFetched": 1, "frontierOmitted": 0, "linksSkipped": 0, "omittedRecords": 0, "truncatedRecords": 0},
            "coverage": {"percent": None, "denominator": None, "scope": "Explicit bounded sources only."},
            "selectionPriority": "Explicit seeds first.", "incomplete": status != "completed",
            "pages": [], "jobs": [], "records": [], "errors": [], "warnings": [], "discovery": None, "searchSlices": [],
        },
    }


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


class ConfigurationTests(unittest.TestCase):
    def test_configuration_validator_is_pure(self):
        with patch("domains.collider.client.httpx.AsyncClient", side_effect=AssertionError("Must not construct client")):
            self.assertEqual(validate_configuration("http://127.0.0.1:58085", TOKEN), "http://127.0.0.1:58085/")
            self.assertEqual(validate_configuration("https://private-service.example/", TOKEN), "https://private-service.example/")
            with self.assertRaises(ColliderConfigurationError):
                validate_configuration("http://attacker.example", TOKEN)

    def test_invalid_configuration_fails_closed(self):
        cases = [
            ("", TOKEN), (None, TOKEN), ("http://example.org", TOKEN),
            ("http://169.254.169.254", TOKEN), ("http://[::1]", TOKEN),
            ("https://user:password@example.org", TOKEN),
            ("https://example.org/path", TOKEN), ("https://example.org?secret=x", TOKEN),
            ("https://example.org#fragment", TOKEN), (" https://example.org", TOKEN),
            ("https://example.org\n", TOKEN), ("https://example.org:0", TOKEN),
            ("https://example.org:70000", TOKEN), ("file:///tmp/a", TOKEN),
            ("http://localhost.evil.example", TOKEN), ("https://example.org", ""),
            ("https://example.org", None), ("https://example.org", "short"),
            ("https://example.org", TOKEN + "\n"),
        ]
        for origin, token in cases:
            with self.subTest(origin=origin), self.assertRaises(ColliderConfigurationError) as caught:
                ColliderClient(origin, token)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_invalid_limits_fail_closed(self):
        for kwargs in ({"timeout_seconds": 0}, {"timeout_seconds": float("nan")}, {"timeout_seconds": float("inf")}, {"timeout_seconds": True}, {"max_response_bytes": 0}, {"max_response_bytes": True}, {"max_response_bytes": 8_388_609}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ColliderConfigurationError):
                ColliderClient("http://localhost:58085", TOKEN, **kwargs)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, handler, **kwargs):
        client = ColliderClient("http://127.0.0.1:58085", TOKEN, transport=httpx.MockTransport(handler), **kwargs)
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_health_and_capabilities(self):
        seen = []
        capabilities = {
            "providers": [{"id": "firecrawl-local", "configured": True}],
            "publicJobBoards": ["greenhouse", "lever", "lever-eu", "ashby"],
            "features": ["durable-collection-runs"], "limits": {"runs": {"maxPagesPerRun": 20}},
            "coverage": {"percent": None, "denominator": None}, "scope": "Single-owner local service.",
        }
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "scope": "Gateway liveness only."} if request.url.path == "/health" else capabilities)
        client = self.make_client(handler)
        self.assertTrue((await client.health())["ok"])
        self.assertEqual(await client.capabilities(), capabilities)
        self.assertEqual([r.url.path for r in seen], ["/health", "/v1/capabilities"])
        for request in seen:
            self.assertEqual(request.headers["authorization"], "Bearer " + TOKEN)
            self.assertEqual(request.headers["accept-encoding"], "identity")
            self.assertNotIn("origin", request.headers)
            self.assertNotIn("cookie", request.headers)

    async def test_submit_fetch_and_actions_use_only_fixed_routes(self):
        seen = []
        def handler(request):
            seen.append(request)
            run = run_fixture("cancelled" if request.url.path.endswith("/cancel") else "queued")
            return httpx.Response(202 if request.url.path == "/v1/runs" else 200, json={"replay": False, "run": run} if request.url.path == "/v1/runs" else {"run": run})
        client = self.make_client(handler)
        submitted = await client.submit_run(INPUT, idempotency_key="fynd:user-1:operation-1")
        self.assertFalse(submitted["replay"])
        self.assertEqual(submitted["run"]["id"], RUN_ID)
        self.assertEqual((await client.get_run(RUN_ID))["id"], RUN_ID)
        self.assertEqual((await client.cancel_run(RUN_ID))["status"], "cancelled")
        self.assertEqual((await client.resume_run(RUN_ID))["status"], "queued")
        self.assertEqual([(r.method, r.url.path) for r in seen], [("POST", "/v1/runs"), ("GET", "/v1/runs/" + RUN_ID), ("POST", "/v1/runs/" + RUN_ID + "/cancel"), ("POST", "/v1/runs/" + RUN_ID + "/resume")])
        self.assertEqual(seen[0].headers["idempotency-key"], "fynd:user-1:operation-1")
        self.assertEqual(json.loads(seen[0].content), INPUT)
        self.assertEqual(seen[2].content, b"{}")
        self.assertEqual(seen[3].content, b"{}")
        self.assertTrue(all(r.url.host == "127.0.0.1" for r in seen))
        self.assertFalse(hasattr(client, "list_runs"))
        self.assertFalse(hasattr(client, "search_evidence"))

    async def test_submit_replay_preserves_same_key_without_automatic_retry(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(202, json={"replay": len(seen) > 1, "run": run_fixture()})
        client = self.make_client(handler)
        await client.submit_run(INPUT, idempotency_key="persisted-key")
        replay = await client.submit_run(INPUT, idempotency_key="persisted-key")
        self.assertTrue(replay["replay"])
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0].headers["idempotency-key"], seen[1].headers["idempotency-key"])

    async def test_rejects_untrusted_paths_and_inputs_without_network(self):
        seen = []
        client = self.make_client(lambda request: seen.append(request))
        for run_id in ("https://attacker.example", RUN_ID + "/cancel", "../", "", None, RUN_ID + "?a=1"):
            for method in (client.get_run, client.cancel_run, client.resume_run):
                with self.subTest(run_id=run_id, method=method), self.assertRaises(ColliderError) as caught:
                    await method(run_id)
                self.assertEqual(caught.exception.status_code, 400)
        for key in (None, "", "has space", "bad\r\nheader", "x" * 129):
            with self.assertRaises(ColliderError):
                await client.submit_run(INPUT, idempotency_key=key)
        for payload in ({}, [], None, {**INPUT, "base_url": "https://attacker.example"}, {"query": float("nan")}, {"query": "x" * 20_000}):
            with self.assertRaises(ColliderError):
                await client.submit_run(payload, idempotency_key="valid-key")
        self.assertEqual(seen, [])

    async def test_no_redirect_or_credential_forwarding(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(307, headers={"location": "https://attacker.example/capture"}, text=TOKEN)
        client = self.make_client(handler)
        with self.assertRaises(ColliderError) as caught:
            await client.get_run(RUN_ID)
        self.assertEqual(len(seen), 1)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn("attacker", str(caught.exception))

    async def test_status_errors_are_sanitized_and_not_retried(self):
        for status, code in ((400, "INVALID_REQUEST"), (401, "UPSTREAM_AUTH"), (403, "UPSTREAM_AUTH"), (404, "UPSTREAM_NOT_FOUND"), (409, "IDEMPOTENCY_CONFLICT"), (413, "UPSTREAM_LIMIT"), (429, "UPSTREAM_CAPACITY"), (500, "UPSTREAM_FAILURE"), (503, "UPSTREAM_FAILURE")):
            seen = []
            def handler(request):
                seen.append(request)
                return httpx.Response(status, text="secret " + TOKEN)
            client = self.make_client(handler)
            with self.subTest(status=status), self.assertRaises(ColliderError) as caught:
                await client.submit_run(INPUT, idempotency_key="fixed-key")
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.uncertain, status >= 500)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertEqual(len(seen), 1)

    async def test_network_error_and_timeout_do_not_expose_details(self):
        for error_type in (httpx.ConnectError, httpx.ReadTimeout):
            seen = []
            def handler(request):
                seen.append(request)
                raise error_type("do not expose " + TOKEN, request=request)
            client = self.make_client(handler)
            with self.assertRaises(ColliderError) as caught:
                await client.submit_run(INPUT, idempotency_key="fixed-key")
            self.assertTrue(caught.exception.uncertain)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertEqual(len(seen), 1)

    async def test_total_timeout_covers_slow_body_and_closes_stream(self):
        stream = TrackingStream([b"{", b"}"], delay=0.04)
        client = self.make_client(lambda _: httpx.Response(202, headers={"content-type": "application/json"}, stream=stream), timeout_seconds=0.01)
        with self.assertRaises(ColliderError) as caught:
            await client.submit_run(INPUT, idempotency_key="fixed-key")
        self.assertEqual(caught.exception.code, "UPSTREAM_TIMEOUT")
        self.assertTrue(caught.exception.uncertain)
        self.assertTrue(stream.closed)

    async def test_response_limit_by_header_and_stream_closes(self):
        for headers in ({"content-length": "9000"}, {}):
            stream = TrackingStream([b"x" * 30, b"x" * 30])
            client = self.make_client(lambda _: httpx.Response(200, headers={"content-type": "application/json", **headers}, stream=stream), max_response_bytes=40)
            with self.assertRaises(ColliderError) as caught:
                await client.get_run(RUN_ID)
            self.assertEqual(caught.exception.code, "RESPONSE_LIMIT")
            self.assertTrue(stream.closed)

    async def test_invalid_json_or_encoding_rejected(self):
        for body, headers in ((b"{", {}), (b"[]", {}), (b"null", {}), (b'{"a":1,"a":2}', {}), (b'{"a":NaN}', {}), (b"\xff", {}), (b"{}", {"content-type": "text/html"}), (b"{}", {"content-encoding": "gzip"})):
            # Stream prevents httpx from eagerly attempting gzip decompression.
            stream = TrackingStream([body])
            client = self.make_client(lambda _: httpx.Response(200, headers={"content-type": "application/json", **headers}, stream=stream))
            with self.subTest(body=body, headers=headers), self.assertRaises(ColliderError) as caught:
                await client.get_run(RUN_ID)
            self.assertEqual(caught.exception.code, "UPSTREAM_RESPONSE")
            self.assertTrue(stream.closed)

    async def test_malformed_runs_fail_closed(self):
        mutations = [
            lambda r: r.pop("result"), lambda r: r.update(id="bad-id"),
            lambda r: r.update(id="32345678-1234-4234-8234-123456789abc"),
            lambda r: r.update(status="100-percent-internet"), lambda r: r.update(status=[]),
            lambda r: r.update(createdAt="yesterday"), lambda r: r.update(allocatedPages=True),
            lambda r: r.update(units=[]), lambda r: r["units"][0].update(kind="remote-code"),
            lambda r: r["units"][0].update(kind={}),
            lambda r: r["progress"].update(done=99), lambda r: r["progress"].update(pending=True),
            lambda r: r["result"]["coverage"].update(percent=100),
            lambda r: r["result"].update(incomplete=False),
            lambda r: r["result"]["counts"].update(savedPages=1),
            lambda r: r["result"].update(pages=["not-a-document"]),
            lambda r: r["result"].update(secret=TOKEN), lambda r: r.update(secret=TOKEN),
        ]
        for mutate in mutations:
            run = run_fixture()
            mutate(run)
            client = self.make_client(lambda _: httpx.Response(200, json={"run": run}))
            with self.subTest(mutation=mutate), self.assertRaises(ColliderError) as caught:
                await client.get_run(RUN_ID)
            self.assertEqual(caught.exception.code, "UPSTREAM_RESPONSE")
            self.assertNotIn(TOKEN, str(caught.exception))

    async def test_bad_write_response_is_uncertain(self):
        for response in ({"replay": "false", "run": run_fixture()}, {"replay": False, "run": {}}, {"success": True}):
            client = self.make_client(lambda _: httpx.Response(202, json=response))
            with self.assertRaises(ColliderError) as caught:
                await client.submit_run(INPUT, idempotency_key="fixed-key")
            self.assertTrue(caught.exception.uncertain)
        client = self.make_client(lambda _: httpx.Response(200, json={"run": {}}))
        with self.assertRaises(ColliderError) as caught:
            await client.cancel_run(RUN_ID)
        self.assertTrue(caught.exception.uncertain)

    async def test_nested_documents_records_and_errors_are_validated(self):
        valid = run_fixture("completed")
        valid["result"]["pages"] = [{"url": "https://example.org/jobs", "id": "a" * 64, "title": "Synthetic page"}]
        valid["result"]["counts"]["savedPages"] = 1
        valid["result"]["records"] = [{"sourceUrl": "https://example.org/jobs", "types": ["Article"], "data": {"headline": "Synthetic only"}}]
        valid["result"]["counts"]["structuredRecords"] = 1
        client = self.make_client(lambda _: httpx.Response(200, json={"run": valid}))
        self.assertEqual((await client.get_run(RUN_ID))["result"]["counts"]["savedPages"], 1)
        for mutate in (
            lambda r: r["result"]["pages"][0].update(url="javascript:alert(1)"),
            lambda r: r["result"]["pages"][0].update(id="not-a-hash"),
            lambda r: r["result"]["pages"][0].update(expired="false"),
            lambda r: r["result"]["records"][0].update(data=[]),
            lambda r: r["result"].update(errors=[{"unitId": UNIT_ID, "code": "secret " + TOKEN}]),
        ):
            response = json.loads(json.dumps(valid))
            mutate(response)
            client = self.make_client(lambda _: httpx.Response(200, json={"run": response}))
            with self.assertRaises(ColliderError) as caught:
                await client.get_run(RUN_ID)
            self.assertEqual(caught.exception.code, "UPSTREAM_RESPONSE")

    async def test_bad_health_capabilities_and_wrong_success_status(self):
        for method, response in (("health", {"ok": False, "scope": "x"}), ("health", {"success": True}), ("capabilities", {"features": []})):
            client = self.make_client(lambda _: httpx.Response(200, json=response))
            with self.subTest(method=method), self.assertRaises(ColliderError):
                await getattr(client, method)()
        client = self.make_client(lambda _: httpx.Response(200, json={"replay": False, "run": run_fixture()}))
        with self.assertRaises(ColliderError):
            await client.submit_run(INPUT, idempotency_key="fixed-key")

    async def test_https_fixed_backend_allowed_and_context_closes(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "scope": "Liveness only."})
        async with ColliderClient("https://private-service.example", TOKEN, transport=httpx.MockTransport(handler)) as client:
            await client.health()
        self.assertEqual(str(seen[0].url), "https://private-service.example/health")
        self.assertTrue(client._http.is_closed)

    async def test_cancellation_propagates_without_masking(self):
        async def handler(request):
            raise asyncio.CancelledError()
        client = self.make_client(handler)
        with self.assertRaises(asyncio.CancelledError):
            await client.get_run(RUN_ID)


if __name__ == "__main__":
    unittest.main()

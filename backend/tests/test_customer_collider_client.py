"""Private-protocol tests with HTTPX MockTransport; no sockets/live providers."""
import asyncio
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import httpx

from domains.collider.customer_client import (
    CustomerColliderClient, CustomerColliderConfigurationError, CustomerColliderError,
    validate_customer_configuration,
)


KEY = "SYNTHETIC_CUSTOMER_SIGNING_KEY_NOT_REAL_123456"
OWNER = "account:synthetic-A"
RUN = "12345678-1234-4234-8234-123456789abc"
UNIT = "22345678-1234-4234-8234-123456789abc"
NONCE = "32345678-1234-4234-8234-123456789abc"
STAMP = 1789387200
NOW = "2026-09-14T12:00:00.000Z"
INPUT = {"urls": ["https://example.org/research"], "pageLimit": 1}
# Generated independently with the actual customerAssertionMessage export from
# collider/customer-auth.mjs and Node 24 createHmac, not Python's signer. Inputs
# are the Unicode payload in test_exact_canonical_signatures... below.
NODE_SIGNATURE = "7d965162d3e154778505534c3a46aa71ebf0bc53dbbd2f4d57afea5081e027f1"
NODE_CHANGED_KEY_SIGNATURE = "ee7608d4d5b609de0df0c06558b1b1ff1ccfc9174530d47ce2be40803143a921"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def run_fixture():
    return {"id": RUN, "input": {**INPUT, "boards": [], "followLinks": False}, "status": "queued",
        "createdAt": NOW, "updatedAt": NOW, "startedAt": None, "finishedAt": None, "cancelRequestedAt": None,
        "allocatedPages": 1, "eventsDropped": 0,
        "units": [{"id": UNIT, "kind": "page", "input": {"url": INPUT["urls"][0]}, "status": "pending", "startedAt": None, "finishedAt": None}],
        "events": [{"at": NOW, "type": "queued"}],
        "progress": {"total": 1, "done": 0, "pending": 1, "inflight": 0, "completed": 0, "partial": 0, "failed": 0, "uncertain": 0},
        "result": {"counts": {"savedPages": 0, "savedJobs": 0, "structuredRecords": 0, "successfulEmptyBoards": 0,
            "selectedPages": 1, "attemptedPages": 0, "discoveredUrls": 1, "notFetched": 1, "frontierOmitted": 0, "linksSkipped": 0,
            "omittedRecords": 0, "truncatedRecords": 0},
            "coverage": {"percent": None, "denominator": None, "scope": "Bounded selected sources."},
            "selectionPriority": "Explicit seeds first.", "incomplete": True,
            "pages": [], "jobs": [], "records": [], "errors": [], "warnings": [], "discovery": None, "searchSlices": []}}


def summary_fixture():
    value = run_fixture()
    del value["units"]; del value["events"]
    value["result"] = {key: value["result"][key] for key in ("counts", "coverage", "selectionPriority", "incomplete")}
    return value


def snapshot_fixture(owner=OWNER):
    binding = ["run-evidence-binding-v1", owner, RUN, UNIT, "page", INPUT["urls"][0]]
    value = {"id": hashlib.sha256(canonical(binding)).hexdigest(), "runId": RUN, "unitId": UNIT, "evidenceKind": "page",
        "url": INPUT["urls"][0], "title": "Synthetic evidence 🌍", "markdown": "# Synthetic evidence\n\n研究 🌍\u2028retained.",
        "provider": "firecrawl-local", "kind": "page", "observedAt": None}
    value["contentHash"] = hashlib.sha256(value["markdown"].encode("utf-8")).hexdigest()
    value["capturedAt"] = NOW
    value["snapshotHash"] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def usage_fixture():
    return {"runs": {"runs": 0, "active": 0, "queued": 0, "paused": 0, "allocatedPages": 0, "storedBytes": 0, "statuses": {},
        "limits": {"maxRuns": 100, "maxPagesPerRun": 20, "maxAllocatedPages": 500, "maxBytesPerRun": 2097152, "maxActive": 1}, "storage": "Logical bytes."},
        "evidence": {"runs": 0, "snapshots": 0, "storedBytes": 0, "limits": {"maxRunsPerOwner": 100, "maxSnapshotsPerRun": 500,
            "maxBytesPerRun": 4194304, "maxBytesPerOwner": 16777216}, "storage": "Logical snapshots."},
        "requests": {"day": "2026-09-14", "reservedRequests": 0, "remainingRequests": 100,
            "limits": {"maxRequestsPerOwnerPerDay": 100, "maxRequestsPerDay": 1000}},
        "queue": {"active": 0, "queued": 0, "closed": False, "limits": {"maxConcurrent": 4, "maxQueued": 100, "maxQueuedPerOwner": 20}},
        "scope": "Owner-only adapter attempts; not billing."}


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks; self.delay = delay; self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


class CustomerClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler, **kwargs):
        value = CustomerColliderClient("https://customer-service.example.org", KEY, owner_id=kwargs.pop("owner_id", OWNER),
            now=kwargs.pop("now", lambda: STAMP), nonce_factory=kwargs.pop("nonce_factory", lambda: NONCE),
            transport=httpx.MockTransport(handler), **kwargs)
        self.addAsyncCleanup(value.aclose)
        return value

    async def error(self, awaitable, code, *, uncertain=False, status=None):
        with self.assertRaises(CustomerColliderError) as caught:
            await awaitable
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.uncertain, uncertain)
        if status is not None:
            self.assertEqual(caught.exception.status_code, status)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertNotIn(OWNER, str(caught.exception))
        self.assertNotIn("PRIVATE_SOURCE_SECRET", str(caught.exception))

    async def test_exact_canonical_signatures_bind_method_path_owner_nonce_timestamp_body_and_key(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(202, json={"replay": False, "run": run_fixture()})

        client = self.client(handler)
        payload = {"query": "研究 opportunities 🌍", "pageLimit": 1}
        await client.submit_run(payload, idempotency_key="persisted-key")
        outgoing = seen[0]
        expected = "\n".join(["LYNK-CUSTOMER-V1", "POST", "/v1/customer/runs", OWNER, str(STAMP), NONCE,
                              "persisted-key", hashlib.sha256(canonical(payload)).hexdigest()])
        self.assertEqual(outgoing.content, canonical(payload))
        self.assertEqual(outgoing.headers["x-lynk-signature"], hmac.new(KEY.encode(), expected.encode(), hashlib.sha256).hexdigest())
        self.assertEqual(outgoing.headers["x-lynk-signature"], NODE_SIGNATURE)
        self.assertEqual(outgoing.headers["x-lynk-owner"], OWNER)
        self.assertEqual(outgoing.headers["x-lynk-timestamp"], str(STAMP))
        self.assertEqual(outgoing.headers["x-lynk-nonce"], NONCE)
        self.assertEqual(outgoing.headers["idempotency-key"], "persisted-key")
        self.assertNotIn("authorization", outgoing.headers); self.assertNotIn("cookie", outgoing.headers)
        self.assertNotIn(KEY, str(outgoing.headers))
        await client.submit_run(payload, idempotency_key="other-key")
        self.assertEqual(seen[1].headers["x-lynk-signature"], NODE_CHANGED_KEY_SIGNATURE)
        self.assertNotEqual(seen[1].headers["x-lynk-signature"], outgoing.headers["x-lynk-signature"],
                            "A mutation cannot reuse a valid assertion with an altered execution key")

    async def test_get_signs_empty_bytes_and_uses_only_exact_fixed_read_paths(self):
        seen = []
        snapshot = snapshot_fixture()

        def handler(request):
            seen.append(request)
            if request.url.path == "/health":
                value = {"ok": True, "scope": "Private customer service."}
            elif request.url.path.endswith("/snapshots/" + snapshot["id"]):
                value = {"snapshot": snapshot}
            elif request.url.path.endswith("/snapshots"):
                value = {"snapshots": [{key: value for key, value in snapshot.items() if key != "markdown"}]}
            elif request.url.path == "/v1/customer/runs":
                value = {"runs": [summary_fixture()]}
            else:
                value = {"run": run_fixture()}
            return httpx.Response(200, json=value)

        client = self.client(handler)
        self.assertTrue((await client.health())["ok"])
        self.assertEqual((await client.list_runs())[0]["id"], RUN)
        self.assertEqual((await client.get_run(RUN))["id"], RUN)
        self.assertEqual((await client.list_snapshots(RUN))[0]["id"], snapshot["id"])
        self.assertEqual(await client.get_snapshot(RUN, snapshot["id"]), snapshot)
        for outgoing in seen:
            self.assertEqual(outgoing.content, b"")
            self.assertNotIn("content-length", outgoing.headers)
            self.assertNotIn("transfer-encoding", outgoing.headers)
            self.assertEqual(outgoing.url.host, "customer-service.example.org")
            self.assertNotIn("idempotency-key", outgoing.headers)
            text = "\n".join(["LYNK-CUSTOMER-V1", "GET", outgoing.url.path, OWNER, str(STAMP), NONCE, "", hashlib.sha256(b"").hexdigest()])
            self.assertEqual(outgoing.headers["x-lynk-signature"], hmac.new(KEY.encode(), text.encode(), hashlib.sha256).hexdigest())

    async def test_actions_sign_exact_empty_json_body_and_do_not_submit_new_runs(self):
        seen = []
        client = self.client(lambda outgoing: seen.append(outgoing) or httpx.Response(200, json={"run": run_fixture()}))
        await client.cancel_run(RUN); await client.resume_run(RUN)
        self.assertEqual([request.url.path for request in seen], [f"/v1/customer/runs/{RUN}/cancel", f"/v1/customer/runs/{RUN}/resume"])
        self.assertTrue(all(request.method == "POST" and request.content == b"{}" for request in seen))

    async def test_explicit_reconciliation_reuses_execution_key_but_gets_fresh_signature_nonce(self):
        seen = []; nonces = iter([NONCE, "42345678-1234-4234-8234-123456789abc"])
        client = self.client(lambda request: seen.append(request) or httpx.Response(202, json={"replay": len(seen) > 1, "run": run_fixture()}), nonce_factory=lambda: next(nonces))
        await client.submit_run(INPUT, idempotency_key="same-persisted-key")
        self.assertTrue((await client.submit_run(INPUT, idempotency_key="same-persisted-key"))["replay"])
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0].headers["idempotency-key"], seen[1].headers["idempotency-key"])
        self.assertNotEqual(seen[0].headers["x-lynk-nonce"], seen[1].headers["x-lynk-nonce"])
        self.assertNotEqual(seen[0].headers["x-lynk-signature"], seen[1].headers["x-lynk-signature"])

    async def test_different_owners_sign_independently_without_browser_auth_forwarding(self):
        seen = []
        for owner in (OWNER, "account:synthetic-B"):
            client = self.client(lambda request: seen.append(request) or httpx.Response(200, json={"runs": []}), owner_id=owner)
            await client.list_runs()
        self.assertNotEqual(seen[0].headers["x-lynk-signature"], seen[1].headers["x-lynk-signature"])
        self.assertTrue(all("cookie" not in request.headers and "authorization" not in request.headers for request in seen))

    async def test_invalid_run_ids_snapshot_ids_and_client_owner_claims_make_no_request(self):
        seen = []; client = self.client(lambda request: seen.append(request))
        for identifier in (None, "", "../", RUN + "/cancel", RUN + "?owner=B", "https://attacker.example"):
            for method in (client.get_run, client.cancel_run, client.resume_run, client.list_snapshots):
                await self.error(method(identifier), "INVALID_REQUEST", status=400)
        for identifier in (None, "", "A" * 64, "../", "x" * 65):
            await self.error(client.get_snapshot(RUN, identifier), "INVALID_REQUEST", status=400)
        for payload in ({}, [], {**INPUT, "ownerId": "B"}, {**INPUT, "base_url": "https://attacker.example"}, {"query": "x" * 20000}, {"query": float("nan")}):
            await self.error(client.submit_run(payload, idempotency_key="valid"), "INVALID_REQUEST", status=400)
        for key in (None, "", "with spaces", "key\n", "x" * 129):
            await self.error(client.submit_run(INPUT, idempotency_key=key), "INVALID_REQUEST", status=400)
        self.assertEqual(seen, [])

        client = self.client(lambda request: seen.append(request))
        await client.aclose(); await client.aclose()
        await self.error(client.list_runs(), "CLIENT_CLOSED", status=503)
        await self.error(client.submit_run(INPUT, idempotency_key="fixed"), "CLIENT_CLOSED", status=503)
        self.assertEqual(seen, [])

    async def test_redirects_and_upstream_error_bodies_never_leak_signatures_or_details(self):
        seen = []
        client = self.client(lambda request: seen.append(request) or httpx.Response(307, headers={"location": "https://attacker.example/capture"}, text=KEY))
        await self.error(client.submit_run(INPUT, idempotency_key="fixed"), "UPSTREAM_FAILURE", uncertain=True)
        self.assertEqual(len(seen), 1)
        for status, code in [(400, "INVALID_REQUEST"), (401, "UPSTREAM_AUTH"), (403, "UPSTREAM_AUTH"), (404, "UPSTREAM_NOT_FOUND"),
                             (409, "UPSTREAM_CONFLICT"), (413, "UPSTREAM_LIMIT"), (429, "UPSTREAM_CAPACITY"), (500, "UPSTREAM_FAILURE")]:
            client = self.client(lambda request: httpx.Response(status, text="PRIVATE_SOURCE_SECRET " + KEY))
            await self.error(client.submit_run(INPUT, idempotency_key="fixed"), code, uncertain=status >= 500)

    async def test_transport_failure_and_slow_stream_are_uncertain_only_for_mutations(self):
        for exception in (httpx.ConnectError, httpx.ReadTimeout):
            def failed(request):
                raise exception("PRIVATE_SOURCE_SECRET", request=request)
            client = self.client(failed)
            code = "UPSTREAM_TIMEOUT" if exception is httpx.ReadTimeout else "UPSTREAM_UNAVAILABLE"
            await self.error(client.submit_run(INPUT, idempotency_key="fixed"), code, uncertain=True)
            await self.error(client.get_run(RUN), code)
        stream = Stream([b"{", b"}"], delay=0.05)
        client = self.client(lambda _: httpx.Response(202, headers={"content-type": "application/json"}, stream=stream), timeout_seconds=0.01)
        await self.error(client.submit_run(INPUT, idempotency_key="fixed"), "UPSTREAM_TIMEOUT", uncertain=True)
        self.assertTrue(stream.closed)

    async def test_response_caps_apply_to_headers_and_stream_and_close_the_response(self):
        for headers in ({"content-length": "99"}, {}):
            stream = Stream([b"x" * 30, b"y" * 30])
            client = self.client(lambda _: httpx.Response(200, headers={"content-type": "application/json", **headers}, stream=stream), max_response_bytes=40)
            await self.error(client.get_run(RUN), "RESPONSE_LIMIT")
            self.assertTrue(stream.closed)

    async def test_duplicate_json_keys_nonfinite_values_invalid_utf8_and_encoded_content_fail_closed(self):
        for content, extra in [(b'{"x":1,"x":2}', {}), (b'{"x":NaN}', {}), (b'{"x":1e999}', {}), (b"\xff", {}), (b"[]", {}),
                               (b'{"x":"\\ud800"}', {}), (b"{}", {"content-encoding": "gzip"}), (b"{}", {"content-type": "text/html"})]:
            stream = Stream([content])
            client = self.client(lambda _: httpx.Response(202, headers={"content-type": "application/json", **extra}, stream=stream))
            await self.error(client.submit_run(INPUT, idempotency_key="fixed"), "UPSTREAM_RESPONSE", uncertain=True)
            self.assertTrue(stream.closed)

    async def test_malformed_run_contract_is_rejected_after_a_mutation_as_uncertain(self):
        for mutate in [lambda value: value.update(id="bad"), lambda value: value.update(status=[]), lambda value: value.pop("units"),
                       lambda value: value["progress"].update(done=9), lambda value: value["result"].update(incomplete=False)]:
            value = run_fixture(); mutate(value)
            client = self.client(lambda _: httpx.Response(202, json={"replay": False, "run": value}))
            await self.error(client.submit_run(INPUT, idempotency_key="fixed"), "UPSTREAM_RESPONSE", uncertain=True)

    async def test_list_summaries_reject_duplicates_detailed_payloads_and_inconsistent_counts(self):
        bad = summary_fixture(); bad["progress"]["done"] = 2
        for rows in ([summary_fixture(), summary_fixture()], [run_fixture()], [bad], [summary_fixture()] * 101):
            client = self.client(lambda _: httpx.Response(200, json={"runs": rows}))
            await self.error(client.list_runs(), "UPSTREAM_RESPONSE")

    async def test_snapshot_body_hash_binding_owner_and_exact_fields_are_verified(self):
        for mutate in [lambda value: value.update(markdown="changed"), lambda value: value.update(contentHash="0" * 64),
                       lambda value: value.update(snapshotHash="0" * 64), lambda value: value.update(runId=UNIT),
                       lambda value: value.update(extra="PRIVATE_SOURCE_SECRET"), lambda value: value.update(observedAt="now")]:
            value = snapshot_fixture(); identifier = value["id"]; mutate(value)
            client = self.client(lambda _: httpx.Response(200, json={"snapshot": value}))
            await self.error(client.get_snapshot(RUN, identifier), "UPSTREAM_RESPONSE")
        foreign = snapshot_fixture(owner="account:other-owner")
        client = self.client(lambda _: httpx.Response(200, json={"snapshot": foreign}))
        await self.error(client.get_snapshot(RUN, foreign["id"]), "UPSTREAM_RESPONSE")

    async def test_snapshot_metadata_cannot_contain_body_or_duplicate_identifiers(self):
        full = snapshot_fixture(); meta = {key: value for key, value in full.items() if key != "markdown"}
        for rows in ([full], [meta, meta], [meta] * 501):
            client = self.client(lambda _: httpx.Response(200, json={"snapshots": rows}))
            await self.error(client.list_snapshots(RUN), "UPSTREAM_RESPONSE")

    async def test_usage_preserves_only_the_expected_owner_scoped_metrics_contract(self):
        client = self.client(lambda _: httpx.Response(200, json={"usage": usage_fixture()}))
        self.assertEqual(await client.usage(), usage_fixture())
        for mutate in [lambda value: value.update(other_owner="PRIVATE_SOURCE_SECRET"), lambda value: value["requests"].update(globalUsed=10),
                       lambda value: value["requests"].update(remainingRequests=-1), lambda value: value["requests"].update(day="not-a-day"),
                       lambda value: value["queue"].update(active=3), lambda value: value["runs"]["statuses"].update(failed=1)]:
            value = usage_fixture(); mutate(value)
            client = self.client(lambda _: httpx.Response(200, json={"usage": value}))
            await self.error(client.usage(), "UPSTREAM_RESPONSE")

    async def test_invalid_clock_and_nonce_never_expose_raw_details(self):
        seen = []
        for kwargs in ({"now": lambda: float("nan")}, {"now": lambda: -1}, {"now": lambda: True},
                       {"nonce_factory": lambda: "not-uuid"}, {"nonce_factory": lambda: NONCE.upper()},
                       {"nonce_factory": lambda: "32345678-1234-1234-8234-123456789abc"}):
            client = self.client(lambda request: seen.append(request), **kwargs)
            await self.error(client.list_runs(), "INVALID_REQUEST", status=400)
        self.assertEqual(seen, [])


class CustomerConfigurationTests(unittest.TestCase):
    def test_configuration_is_pure_https_and_never_constructs_a_client(self):
        with patch("domains.collider.customer_client.httpx.AsyncClient", side_effect=AssertionError("no network construction")):
            self.assertEqual(validate_customer_configuration("https://private-service.example.org", KEY, OWNER), "https://private-service.example.org/")
        for url in [None, "", "http://127.0.0.1:9999", "http://example.org", "https://user:password@example.org", "https://example.org/path",
                    "https://example.org?secret=x", "https://example.org#fragment", "https://example.org?", "https://example.org#", "https://example.org/?", "https://example.org/#",
                    "https://example.org\n", " https://example.org", "https://example.org:0", "https://example.org:70000", "file:///tmp/private"]:
            with self.subTest(url=url), self.assertRaises(CustomerColliderConfigurationError):
                validate_customer_configuration(url, KEY, OWNER)

    def test_invalid_keys_owners_and_resource_limits_fail_before_client_construction(self):
        for key in [None, "", "short", "x" * 129, KEY + "\n"]:
            with self.assertRaises(CustomerColliderConfigurationError):
                validate_customer_configuration("https://service.example.org", key, OWNER)
        for owner in [None, "", "../owner", "with space", "x" * 129, {"id": "A"}]:
            with self.assertRaises(CustomerColliderConfigurationError):
                validate_customer_configuration("https://service.example.org", KEY, owner)
        for kwargs in [{"timeout_seconds": 0}, {"timeout_seconds": True}, {"timeout_seconds": float("inf")},
                       {"max_response_bytes": 0}, {"max_response_bytes": 8388609}, {"max_response_bytes": True}, {"now": None}, {"nonce_factory": None}]:
            with self.assertRaises(CustomerColliderConfigurationError):
                CustomerColliderClient("https://service.example.org", KEY, owner_id=OWNER, **kwargs)


if __name__ == "__main__":
    unittest.main()

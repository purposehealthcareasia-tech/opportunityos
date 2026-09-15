"""Synthetic Motor-style collection tests. No Mongo, sockets, disk or fixtures."""
import asyncio
import copy
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from domains.research_reports.service import ResearchReportError, ResearchReportService


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
OWNER_A = "user:A"
OWNER_B = "user:B"


def bundle(title="Saved research", content="Retained synthetic evidence."):
    return {"manifest": {"schemaVersion": 1, "title": title, "omissions": ["Imported evidence only."], "warnings": []},
            "files": {"evidence.jsonl": json.dumps({"url": "https://example.org/evidence", "content": content}, ensure_ascii=False) + "\n",
                      "candidates.jsonl": "", "outcomes.jsonl": "", "edges.jsonl": ""}}


class DuplicateKey(Exception):
    code = 11000


class FakeCollection:
    """Minimal atomic implementation of precisely the Mongo operators in use.

    Every database call yields first, so parallel service coroutines share stale
    reads. The lock is acquired only for the individual database operation, not
    across the service's read/update sequence. Thus tests catch count-then-write
    races instead of accidentally serializing the whole service workflow.
    """
    def __init__(self):
        self.documents = {}
        self.lock = asyncio.Lock()
        self.calls = []
        self.duplicate_initialization = False
        self.fail_after_append = False
        self.failure = None

    def expression(self, item, document):
        if isinstance(item, str) and item.startswith("$"):
            return document[item[1:]]
        if not isinstance(item, dict):
            return item
        if set(item) == {"$size"}:
            return len(self.expression(item["$size"], document))
        if set(item) == {"$add"}:
            return sum(self.expression(value, document) for value in item["$add"])
        if set(item) == {"$and"}:
            return all(self.expression(value, document) for value in item["$and"])
        for key, comparison in (("$lt", lambda a, b: a < b), ("$lte", lambda a, b: a <= b)):
            if set(item) == {key}:
                a, b = item[key]
                return comparison(self.expression(a, document), self.expression(b, document))
        raise AssertionError("Unexpected expression operator")

    def matches(self, query, document):
        if document is None:
            return False
        for key, value in query.items():
            if key == "$expr":
                if not self.expression(value, document):
                    return False
            elif key.startswith("reports."):
                assert set(value) == {"$ne"}
                field = key.split(".", 1)[1]
                if any(row.get(field) == value["$ne"] for row in document["reports"]):
                    return False
            elif key == "reports":
                assert set(value) == {"$elemMatch"}
                if not any(all(row.get(field) == expected for field, expected in value["$elemMatch"].items()) for row in document["reports"]):
                    return False
            elif isinstance(value, dict):
                assert set(value) == {"$gte"}
                if document[key] < value["$gte"]:
                    return False
            elif document.get(key) != value:
                return False
        return True

    async def find_one(self, query):
        await asyncio.sleep(0)
        async with self.lock:
            self.calls.append(("find_one", copy.deepcopy(query)))
            if self.failure:
                raise self.failure
            document = self.documents.get(query["_id"])
            return copy.deepcopy(document) if self.matches(query, document) else None

    async def update_one(self, query, update, upsert=False):
        await asyncio.sleep(0)
        async with self.lock:
            self.calls.append(("update_one", copy.deepcopy(query), copy.deepcopy(update), upsert))
            if self.failure:
                raise self.failure
            document = self.documents.get(query["_id"])
            if document is None and upsert:
                assert set(update) == {"$setOnInsert"}
                self.documents[query["_id"]] = {"_id": query["_id"], **copy.deepcopy(update["$setOnInsert"])}
                if self.duplicate_initialization:
                    self.duplicate_initialization = False
                    raise DuplicateKey("synthetic competing initializer")
                return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=query["_id"])
            if not self.matches(query, document):
                return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=None)
            if "$setOnInsert" in update:
                return SimpleNamespace(modified_count=0, matched_count=1, upserted_id=None)
            changed = copy.deepcopy(document)
            if "$push" in update:
                assert set(update["$push"]) == {"reports"}
                changed["reports"].append(copy.deepcopy(update["$push"]["reports"]))
            if "$pull" in update:
                condition = update["$pull"]["reports"]
                changed["reports"] = [row for row in changed["reports"] if not all(row.get(field) == expected for field, expected in condition.items())]
            for field, increment in update.get("$inc", {}).items():
                changed[field] += increment
            self.documents[query["_id"]] = changed
            if "$push" in update and self.fail_after_append:
                self.fail_after_append = False
                raise TimeoutError("SYNTHETIC_INTERNAL_DATABASE_TRACE")
            return SimpleNamespace(modified_count=int(changed != document), matched_count=1, upserted_id=None)


class ResearchReportServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.collection = FakeCollection()
        self.service = ResearchReportService(self.collection, now=lambda: NOW)

    async def assert_code(self, awaitable, code, status):
        with self.assertRaises(ResearchReportError) as caught:
            await awaitable
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.status, status)
        return str(caught.exception)

    async def test_exact_public_envelopes_and_immutable_roundtrip(self):
        original = bundle()
        saved = await self.service.save(OWNER_A, original)
        self.assertEqual(set(saved), {"report", "replay"})
        metadata = saved["report"]
        self.assertEqual(set(metadata), {"id", "title", "saved_at", "byte_size"})
        self.assertFalse(saved["replay"])
        self.assertEqual(metadata["saved_at"], "2026-09-13T12:00:00.000Z")
        listing = await self.service.list(OWNER_A)
        self.assertEqual(listing, {"reports": [metadata], "used_bytes": metadata["byte_size"],
            "limits": {"max_reports": 20, "max_report_bytes": 8388608, "max_total_bytes": 10485760}})
        loaded = await self.service.get(OWNER_A, metadata["id"].upper())
        self.assertEqual(loaded, {"report": {**metadata, "bundle": original}})
        self.assertNotIn("content_hash", json.dumps(loaded))
        self.assertNotIn("user:A", json.dumps(loaded))
        loaded["report"]["bundle"]["manifest"]["title"] = "caller mutation"
        original["manifest"]["title"] = "input mutation"
        self.assertEqual((await self.service.get(OWNER_A, metadata["id"]))["report"]["bundle"]["manifest"]["title"], "Saved research")

    async def test_canonical_envelope_order_deduplicates_without_rewriting_metadata(self):
        original = bundle()
        saved = await self.service.save(OWNER_A, original)
        reordered = {"files": dict(reversed(list(original["files"].items()))), "manifest": dict(reversed(list(original["manifest"].items())))}
        other_service = ResearchReportService(self.collection, now=lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
        replay = await other_service.save(OWNER_A, reordered)
        self.assertEqual(replay, {**saved, "replay": True})
        self.assertEqual(len(self.collection.documents[OWNER_A]["reports"]), 1)

    async def test_same_content_is_independent_per_owner_and_foreign_ids_are_generic_missing(self):
        saved_a = await self.service.save(OWNER_A, bundle())
        saved_b = await self.service.save(OWNER_B, bundle())
        a_id, b_id = saved_a["report"]["id"], saved_b["report"]["id"]
        self.assertNotEqual(a_id, b_id)
        errors = []
        for owner, identifier in [(OWNER_B, a_id), (OWNER_A, b_id), ("user:C", a_id), (OWNER_A, str(uuid4()))]:
            errors.append(await self.assert_code(self.service.get(owner, identifier), "RESEARCH_REPORT_NOT_FOUND", 404))
            errors.append(await self.assert_code(self.service.delete(owner, identifier), "RESEARCH_REPORT_NOT_FOUND", 404))
        self.assertEqual(len(set(errors)), 1)
        self.assertEqual(len((await self.service.list(OWNER_A))["reports"]), 1)
        self.assertEqual(len((await self.service.list(OWNER_B))["reports"]), 1)
        self.assertEqual((await self.service.list("user:C"))["reports"], [])

    async def test_concurrent_duplicate_saves_allocate_exactly_once_even_with_initialization_collision(self):
        self.collection.duplicate_initialization = True
        results = await asyncio.gather(*(self.service.save(OWNER_A, bundle()) for _ in range(15)))
        self.assertEqual(sum(not result["replay"] for result in results), 1)
        self.assertEqual(len({result["report"]["id"] for result in results}), 1)
        bucket = self.collection.documents[OWNER_A]
        self.assertEqual(len(bucket["reports"]), 1)
        self.assertEqual(bucket["used_bytes"], results[0]["report"]["byte_size"])

    async def test_concurrent_distinct_saves_use_atomic_count_conditions(self):
        service = ResearchReportService(self.collection, max_reports=3, now=lambda: NOW)
        results = await asyncio.gather(*(service.save(OWNER_A, bundle(title=f"Report {number}")) for number in range(12)), return_exceptions=True)
        successes = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, ResearchReportError)]
        self.assertEqual(len(successes), 3)
        self.assertEqual(len(failures), 9)
        self.assertTrue(all(failure.code == "RESEARCH_REPORT_QUOTA" for failure in failures))
        bucket = self.collection.documents[OWNER_A]
        self.assertEqual(len(bucket["reports"]), 3)
        self.assertEqual(bucket["used_bytes"], sum(report["byte_size"] for report in bucket["reports"]))
        pushes = [call for call in self.collection.calls if call[0] == "update_one" and "$push" in call[2]]
        self.assertTrue(pushes)
        self.assertTrue(all("$expr" in call[1] and "reports.content_hash" in call[1] and call[1]["_id"] == OWNER_A for call in pushes))

    async def test_concurrent_byte_quota_cannot_be_exceeded(self):
        measured = await self.service.save("measure", bundle(title="Report 0"))
        size = measured["report"]["byte_size"]
        service = ResearchReportService(self.collection, max_owner_bytes=size * 2, now=lambda: NOW)
        results = await asyncio.gather(*(service.save(OWNER_A, bundle(title=f"Report {number}")) for number in range(9)), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 2)
        self.assertEqual(self.collection.documents[OWNER_A]["used_bytes"], size * 2)
        self.assertTrue(all(isinstance(result, dict) or (isinstance(result, ResearchReportError) and result.code == "RESEARCH_REPORT_QUOTA") for result in results))

    async def test_replay_succeeds_at_quota_and_delete_frees_quota_once(self):
        service = ResearchReportService(self.collection, max_reports=1, now=lambda: NOW)
        saved = await service.save(OWNER_A, bundle())
        self.assertTrue((await service.save(OWNER_A, bundle()))["replay"])
        await self.assert_code(service.save(OWNER_A, bundle(title="Different")), "RESEARCH_REPORT_QUOTA", 413)
        results = await asyncio.gather(*(service.delete(OWNER_A, saved["report"]["id"]) for _ in range(10)), return_exceptions=True)
        self.assertEqual(sum(result == {"deleted": True} for result in results), 1)
        self.assertTrue(all(result == {"deleted": True} or (isinstance(result, ResearchReportError) and result.status == 404) for result in results))
        self.assertEqual((await service.list(OWNER_A))["used_bytes"], 0)
        self.assertFalse((await service.save(OWNER_A, bundle(title="Different")))["replay"])

    async def test_uncertain_database_response_is_sanitized_and_exact_retry_replays(self):
        self.collection.fail_after_append = True
        message = await self.assert_code(self.service.save(OWNER_A, bundle()), "RESEARCH_REPORT_STORAGE_UNAVAILABLE", 503)
        self.assertNotIn("SYNTHETIC_INTERNAL", message)
        replay = await self.service.save(OWNER_A, bundle())
        self.assertTrue(replay["replay"])
        self.assertEqual(len(self.collection.documents[OWNER_A]["reports"]), 1)

    async def test_owner_and_report_identifiers_are_validated_before_database_access(self):
        for invalid in [None, {}, {"$ne": ""}, "", "../owner", "has space", "x" * 129, "owner\n"]:
            for method, args in [(self.service.save, (bundle(),)), (self.service.list, ()), (self.service.get, (str(uuid4()),)), (self.service.delete, (str(uuid4()),))]:
                await self.assert_code(method(invalid, *args), "RESEARCH_REPORT_INVALID", 400)
        for invalid in [None, "", "../report", "/reports/" + str(uuid4()), str(uuid4()) + "?owner=B"]:
            await self.assert_code(self.service.get(OWNER_A, invalid), "RESEARCH_REPORT_INVALID", 400)
            await self.assert_code(self.service.delete(OWNER_A, invalid), "RESEARCH_REPORT_INVALID", 400)
        self.assertEqual(self.collection.calls, [])

    async def test_strict_compact_envelope_rejects_unknown_fields_and_client_ownership_claims(self):
        variants = []
        for field in ["owner", "ownerId", "user_id", "tenant_id"]:
            value = bundle(); value[field] = OWNER_B; variants.append(value)
            value = bundle(); value["files"]["evidence.jsonl"] = json.dumps({field: OWNER_B}); variants.append(value)
        value = bundle(); value["files"]["evidence.csv"] = "a,b"; variants.append(value)
        value = bundle(); del value["files"]["edges.jsonl"]; variants.append(value)
        value = bundle(); value["manifest"]["internetCoveragePercent"] = 100; variants.append(value)
        value = bundle(); value["manifest"]["schemaVersion"] = True; variants.append(value)
        value = bundle(); value["manifest"]["title"] = "x" * 501; variants.append(value)
        value = bundle(); value["manifest"]["warnings"] = ["x"] * 1001; variants.append(value)
        value = bundle(); value["manifest"]["omissions"] = ["x"] * 1001; variants.append(value)
        value = bundle(); value["manifest"]["omissions"] = ["x" * 1001]; variants.append(value)
        value = bundle(); value["manifest"]["runSummary"] = []; variants.append(value)
        value = bundle(); value["files"]["evidence.jsonl"] = []; variants.append(value)
        for value in variants:
            await self.assert_code(self.service.save(OWNER_A, value), "RESEARCH_REPORT_INVALID", 400)
        self.assertEqual(self.collection.calls, [])

    async def test_diagnostic_arrays_preserve_up_to_one_thousand_entries_without_truncation(self):
        value = bundle()
        value["manifest"]["warnings"] = [f"Warning {number}" for number in range(1000)]
        value["manifest"]["omissions"] = [f"Omission {number}" for number in range(1000)]
        saved = await self.service.save(OWNER_A, value)
        loaded = await self.service.get(OWNER_A, saved["report"]["id"])
        self.assertEqual(loaded["report"]["bundle"], value)
        self.assertEqual(len(loaded["report"]["bundle"]["manifest"]["warnings"]), 1000)
        self.assertEqual(len(loaded["report"]["bundle"]["manifest"]["omissions"]), 1000)

    async def test_all_c0_and_del_title_controls_are_rejected_before_database_access(self):
        for codepoint in [*range(32), 127]:
            with self.subTest(codepoint=codepoint):
                await self.assert_code(self.service.save(OWNER_A, bundle(title=f"Report{chr(codepoint)}title")), "RESEARCH_REPORT_INVALID", 400)
        self.assertEqual(self.collection.calls, [])

    async def test_jsonl_rejects_malformed_duplicate_nonfinite_and_nonobject_values(self):
        for text in ["{bad}", "[]", "null", "42", '{"same":1,"same":2}', '{"value":NaN}', '{"value":Infinity}', '{"value":1e999}', '{"__proto__":{}}', '{"value":"\\ud800"}']:
            value = bundle(); value["files"]["evidence.jsonl"] = text
            await self.assert_code(self.service.save(OWNER_A, value), "RESEARCH_REPORT_INVALID", 400)
        self.assertEqual(self.collection.calls, [])

    async def test_json_depth_nodes_and_record_limits_are_bounded(self):
        deep = {}
        for _ in range(22):
            deep = {"nested": deep}
        variants = [json.dumps(deep), json.dumps({"rows": [0] * 5001}), "\n".join('{"rows":' + json.dumps([0] * 200) + '}' for _ in range(1000)), "\n".join("{}" for _ in range(1001))]
        for text in variants:
            value = bundle(); value["files"]["evidence.jsonl"] = text
            await self.assert_code(self.service.save(OWNER_A, value), "RESEARCH_REPORT_INVALID", 400)
        value = bundle(); value["files"]["candidates.jsonl"] = "{}\n" * 3000; value["files"]["edges.jsonl"] = "{}\n" * 2001
        await self.assert_code(self.service.save(OWNER_A, value), "RESEARCH_REPORT_INVALID", 400)
        self.assertEqual(self.collection.calls, [])

    async def test_maximum_line_counts_and_empty_run_summary_are_storage_only(self):
        value = bundle(); value["files"]["evidence.jsonl"] = "{}\n" * 1000
        value["files"]["candidates.jsonl"] = "{}\n" * 2500; value["files"]["outcomes.jsonl"] = "{}\n" * 2500
        saved = await self.service.save(OWNER_A, value)
        self.assertEqual((await self.service.get(OWNER_A, saved["report"]["id"]))["report"]["bundle"], value)
        empty = bundle(title="Zero results"); empty["files"]["evidence.jsonl"] = ""
        await self.assert_code(self.service.save(OWNER_A, empty), "RESEARCH_REPORT_INVALID", 400)
        empty["manifest"]["runSummary"] = {"format": "lynk-collider-run-v1", "status": "failed"}
        stored = await self.service.save(OWNER_A, empty)
        self.assertEqual((await self.service.get(OWNER_A, stored["report"]["id"]))["report"]["bundle"], empty)

    async def test_utf8_bytes_unicode_separators_and_inert_source_text_are_preserved(self):
        content = '研究 🌍\u2028second paragraph <script>doNotExecute()</script> https://127.0.0.1/private'
        value = bundle(content=content)
        saved = await self.service.save(OWNER_A, value)
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(saved["report"]["byte_size"], len(canonical.encode("utf-8")))
        self.assertEqual((await self.service.get(OWNER_A, saved["report"]["id"]))["report"]["bundle"], value)
        self.assertGreater(saved["report"]["byte_size"], len(canonical))

    async def test_snapshot_size_rejection_does_not_create_owner_bucket(self):
        service = ResearchReportService(self.collection, max_snapshot_bytes=500)
        await self.assert_code(service.save(OWNER_A, bundle(content="界" * 300)), "RESEARCH_REPORT_TOO_LARGE", 413)
        self.assertEqual(self.collection.calls, [])

    async def test_malformed_configuration_cannot_raise_hard_mongo_storage_limits(self):
        for values in [{"max_reports": 21}, {"max_reports": True}, {"max_reports": 0}, {"max_snapshot_bytes": 8388609},
                       {"max_owner_bytes": 10485761}, {"max_owner_bytes": float("inf")}, {"now": "not callable"}]:
            with self.subTest(values=values), self.assertRaises(ResearchReportError) as caught:
                ResearchReportService(self.collection, **values)
            self.assertEqual(caught.exception.code, "RESEARCH_REPORT_CONFIGURATION")
        self.assertEqual(self.collection.calls, [])

    async def test_corrupt_stored_hash_payload_and_counters_fail_closed(self):
        saved = await self.service.save(OWNER_A, bundle())
        pristine = copy.deepcopy(self.collection.documents[OWNER_A])
        mutations = [lambda row: row.update(used_bytes=0), lambda row: row["reports"][0].update(payload="{}"),
                     lambda row: row["reports"][0].update(content_hash="0" * 64), lambda row: row["reports"][0].update(title="changed")]
        for mutate in mutations:
            self.collection.documents[OWNER_A] = copy.deepcopy(pristine); mutate(self.collection.documents[OWNER_A])
            await self.assert_code(self.service.get(OWNER_A, saved["report"]["id"]), "RESEARCH_REPORT_STORAGE_INVALID", 503)
            await self.assert_code(self.service.list(OWNER_A), "RESEARCH_REPORT_STORAGE_INVALID", 503)
            await self.assert_code(self.service.delete(OWNER_A, saved["report"]["id"]), "RESEARCH_REPORT_STORAGE_INVALID", 503)

    async def test_database_errors_never_return_raw_details(self):
        self.collection.failure = RuntimeError("SYNTHETIC_DATABASE_SECRET owner=A payload=private")
        for awaitable in [self.service.save(OWNER_A, bundle()), self.service.list(OWNER_A), self.service.get(OWNER_A, str(uuid4())), self.service.delete(OWNER_A, str(uuid4()))]:
            message = await self.assert_code(awaitable, "RESEARCH_REPORT_STORAGE_UNAVAILABLE", 503)
            self.assertNotIn("SYNTHETIC_DATABASE_SECRET", message)

    async def test_server_uuid_collision_cannot_overwrite_an_existing_report(self):
        identifier = uuid4()
        service = ResearchReportService(self.collection, now=lambda: NOW, id_factory=lambda: identifier)
        saved = await service.save(OWNER_A, bundle())
        await self.assert_code(service.save(OWNER_A, bundle(title="Different payload")), "RESEARCH_REPORT_CONFLICT", 409)
        self.assertEqual((await service.get(OWNER_A, saved["report"]["id"]))["report"]["title"], "Saved research")
        self.assertEqual(len(self.collection.documents[OWNER_A]["reports"]), 1)


if __name__ == "__main__":
    unittest.main()

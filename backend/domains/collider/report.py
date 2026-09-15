"""Pure, bounded handoff from one owner-scoped Collider run to Fynd Research.

The caller must obtain all three inputs through the same authenticated customer
handle. This module has no network, storage, latest-index, or owner-selection API.
Hashes check accidental substitution/corruption, not publisher truth or identity.
The compact bundle retains exact snapshot bodies. Fynd's existing display/import
normalizer may trim text and omits unsupported snapshot-provenance fields.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from datetime import datetime
from urllib.parse import urlsplit

from .client import _validate_run


MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOTS = 500
MAX_RECORDS = 1000
MAX_TRACE = 5000
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
HASH = re.compile(r"[0-9a-f]{64}")
LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}")
SNAPSHOT_FIELDS = ("id", "runId", "unitId", "evidenceKind", "url", "title",
                   "markdown", "provider", "kind", "observedAt", "contentHash", "capturedAt")
METADATA_FIELDS = set(SNAPSHOT_FIELDS) - {"markdown"} | {"snapshotHash"}
UNSAFE_KEYS = {"__proto__", "constructor", "prototype", "owner", "ownerId", "owner_id",
               "userId", "user_id", "tenantId", "tenant_id"}


class ColliderReportError(RuntimeError):
    """Safe failure only; never echo upstream data or exception details."""

    def __init__(self, code="REPORT_INVALID", status_code=502):
        self.code = code
        self.status_code = status_code
        super().__init__("Collider report could not be assembled.")


def _invalid():
    raise ColliderReportError()


def _large():
    raise ColliderReportError("REPORT_TOO_LARGE", 413)


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError, UnicodeError):
        _invalid()


def _utf8(value):
    try:
        return value.encode("utf-8")
    except UnicodeError:
        _invalid()


def _bounded(value):
    nodes = 0

    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 150000 or depth > 20:
            _invalid()
        if type(item) is dict:
            for key, child in item.items():
                if not isinstance(key, str) or key in UNSAFE_KEYS or len(key) > 500:
                    _invalid()
                _utf8(key)
                visit(child, depth + 1)
        elif type(item) is list:
            if len(item) > 5000:
                _invalid()
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if len(item) > MAX_INPUT_BYTES:
                _large()
            _utf8(item)
        elif item is not None and type(item) not in (bool, int, float):
            _invalid()
        elif type(item) is float and not math.isfinite(item):
            _invalid()

    visit(value)
    if len(_utf8(_json(value))) > MAX_INPUT_BYTES:
        _large()


def _text(value, maximum, *, empty=True, multiline=False):
    controls = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]" if multiline else r"[\x00-\x1f\x7f-\x9f]"
    if not isinstance(value, str) or (not empty and not value.strip()) or re.search(controls, value):
        _invalid()
    # Match the source vault's JavaScript UTF-16 limits, including emoji.
    try:
        if len(value.encode("utf-16-le")) // 2 > maximum:
            _invalid()
    except UnicodeError:
        _invalid()
    return value


def _url(value):
    _text(value, 2048, empty=False)
    if re.search(r"[\x00-\x20\\]", value):
        _invalid()
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
            _invalid()
        if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host) or host.endswith("."):
            _invalid()
        if any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") for part in host.split(".")):
            _invalid()
        if re.search(r"(^|\.)(localhost|local|internal|intranet|lan|home|test|invalid|example|onion)$", host) or re.search(r"(^|\.)(nip\.io|sslip\.io|localtest\.me)$", host):
            _invalid()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            _invalid()
    except (ValueError, TypeError):
        _invalid()
    return value


def _stamp(value, nullable=False):
    if nullable and value is None:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        _invalid()
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _invalid()
    return value


def _metadata(value, run_id, unit_ids):
    if type(value) is not dict or set(value) != METADATA_FIELDS or value.get("runId") != run_id or value.get("unitId") not in unit_ids:
        _invalid()
    for key in ("id", "contentHash", "snapshotHash"):
        if not isinstance(value[key], str) or not HASH.fullmatch(value[key]):
            _invalid()
    for key in ("evidenceKind", "provider", "kind"):
        if not isinstance(value[key], str) or not LABEL.fullmatch(value[key]):
            _invalid()
    _url(value["url"])
    _text(value["title"], 500)
    _stamp(value["observedAt"], True)
    _stamp(value["capturedAt"])
    return value


def _summary(run):
    result = run["result"]
    supplied = run["input"]
    if type(supplied.get("urls")) is not list or len(supplied["urls"]) > 20 or type(supplied.get("boards")) is not list or len(supplied["boards"]) > 3 or type(supplied.get("pageLimit")) is not int or not 1 <= supplied["pageLimit"] <= 20 or type(supplied.get("followLinks")) is not bool:
        _invalid()
    for url in supplied["urls"]:
        _url(url)
    for board in supplied["boards"]:
        if type(board) is not dict or set(board) - {"provider", "board", "limit"}:
            _invalid()
        _text(board.get("provider"), 50, empty=False)
        _text(board.get("board"), 80, empty=False)
        if "limit" in board and (type(board["limit"]) is not int or not 0 <= board["limit"] <= 100):
            _invalid()
    if "query" in supplied:
        _text(supplied["query"], 400, empty=False)
    if not supplied["urls"] and not supplied["boards"] and not supplied.get("query"):
        _invalid()
    for name, maximum, length in (("providers", 4, 50), ("querySlices", 3, 400)):
        if name in supplied:
            if type(supplied[name]) is not list or len(supplied[name]) > maximum:
                _invalid()
            for value in supplied[name]:
                _text(value, length, empty=False)
    if "maxDepth" in supplied and (type(supplied["maxDepth"]) is not int or not 0 <= supplied["maxDepth"] <= 2):
        _invalid()
    if "crawlMode" in supplied and supplied["crawlMode"] not in ("jobs", "web"):
        _invalid()
    _text(result["coverage"].get("scope", ""), 1000)
    _text(result["selectionPriority"], 1000)
    for row in result["errors"] + result["warnings"]:
        _text(row.get("source", ""), 200)
        if row.get("url"):
            _url(row["url"])
    for slice_ in result["searchSlices"]:
        _text(slice_["query"], 400)
        for provider in slice_["providers"]:
            if type(provider) is not dict:
                _invalid()
            for key, maximum in (("id", 50), ("status", 80), ("code", 100)):
                _text(provider.get(key, ""), maximum)
            if "returned" in provider and (type(provider["returned"]) is not int or not 0 <= provider["returned"] <= 9007199254740991):
                _invalid()
    summary = {"format": "lynk-collider-run-v1", "id": run["id"], "status": run["status"],
               "input": run["input"], "progress": run["progress"], "counts": result["counts"],
               "incomplete": result["incomplete"], "createdAt": run["createdAt"],
               "updatedAt": run["updatedAt"], "finishedAt": run["finishedAt"],
               "coverageScope": result["coverage"].get("scope", ""),
               "selectionPriority": result["selectionPriority"],
               "errors": result["errors"], "warnings": result["warnings"],
               "searchSlices": [{key: value for key, value in row.items() if key != "results"} for row in result["searchSlices"]]}
    return json.loads(_json(summary))


def assemble_report(run, snapshot_metadata, snapshot_details, *, expected_run_id):
    """Return a compact Research bundle from unwrapped customer endpoint data.

    Supply every item listed by ``{snapshots: metadata[]}`` with its corresponding
    detail from ``{snapshot: ...}``, after the HTTP client validates the envelopes.
    Any absent, extra, cross-run/unit, or changed item fails the whole assembly;
    callers retain the previous report. A source read explicitly not retained by
    Collider is represented as metadata, never refetched or filled from a cache.
    """
    if not isinstance(expected_run_id, str) or not UUID.fullmatch(expected_run_id):
        _invalid()
    _bounded([run, snapshot_metadata, snapshot_details])
    try:
        _validate_run(run, expected_run_id)
    except Exception:
        _invalid()
    summary = _summary(run)
    units = {unit["id"]: unit for unit in run["units"]}
    listed = snapshot_metadata
    if type(listed) is not list or len(listed) > MAX_SNAPSHOTS or type(snapshot_details) is not list or len(snapshot_details) != len(listed):
        _invalid()
    metadata = {}
    for row in listed:
        _metadata(row, expected_run_id, units)
        if row["id"] in metadata:
            _invalid()
        metadata[row["id"]] = row
    snapshots = {}
    for row in snapshot_details:
        if type(row) is not dict or set(row) != set(SNAPSHOT_FIELDS) | {"snapshotHash"}:
            _invalid()
        meta = {key: value for key, value in row.items() if key != "markdown"}
        _metadata(meta, expected_run_id, units)
        if row["id"] not in metadata or meta != metadata[row["id"]] or row["id"] in snapshots:
            _invalid()
        body = _text(row["markdown"], 60000, multiline=True)
        if hashlib.sha256(_utf8(body)).hexdigest() != row["contentHash"]:
            _invalid()
        signed = {key: row[key] for key in SNAPSHOT_FIELDS}
        if hashlib.sha256(_utf8(_json(signed))).hexdigest() != row["snapshotHash"]:
            _invalid()
        snapshots[row["id"]] = row

    omissions = ["Only immutable snapshots listed for this customer run supply source bodies; no latest-URL index was read.",
                 "A retained body is not a full-content, freshness, independent-verification, or internet-coverage claim.",
                 "No crawl edges or unrecorded discoveries were reconstructed. Missing upstream lineage remains unavailable.",
                 "The compact bundle retains exact snapshot text and hashes; Research display/import normalization may trim text and omit snapshot-provenance fields.",
                 "Research display/import normalizes source URLs, including removing fragments; original snapshot URLs remain in this compact bundle.",
                 "Publisher job data is a publisher claim; it does not prove the destination job page was fetched.",
                 "Run saved-page/job counts describe runtime metadata, not the number of independently fetched bodies in this report."]
    records = []
    for row in sorted(snapshots.values(), key=lambda item: (item["capturedAt"], item["id"])):
        records.append({"sourceId": row["id"], "url": row["url"], "title": row["title"],
                        "kind": "web" if row["kind"] == "page" else row["kind"],
                        "content": row["markdown"], "contentStatus": "unknown" if row["markdown"].strip() else "metadata-only",
                        "source": row["provider"], "retainedSnapshot": metadata[row["id"]]})

    fallback_count = derived_count = 0
    for category in ("pages", "jobs"):
        for position, document in enumerate(run["result"][category]):
            _url(document["url"])
            ref = document.get("evidenceSnapshotId")
            if document.get("evidenceRetention") == "retained":
                if ref not in snapshots:
                    _invalid()
                retained = snapshots[ref]
                # Current runtime page metadata omits evidenceKind; the page
                # category and retained snapshot must still agree. Jobs carry
                # an explicit kind because a job can reference a fetched page.
                declared_kind = document.get("evidenceKind", "page" if category == "pages" else None)
                if retained["url"] != document["url"] or retained["evidenceKind"] != declared_kind or ("contentHash" in document and retained["contentHash"] != document["contentHash"]):
                    _invalid()
                if category == "pages" or retained["kind"] == "job":
                    continue
                derived_count += 1
            elif ref is not None or document.get("evidenceRetention") != "not-retained":
                _invalid()
            else:
                fallback_count += 1
            records.append({"sourceId": f"{expected_run_id}:{category}:{position}", "url": document["url"],
                            "title": document.get("title", ""), "kind": "jobs" if category == "jobs" else "web",
                            "contentStatus": "metadata-only", "source": document.get("source") or document.get("provider", ""),
                            "evidenceSnapshotId": ref, "evidenceRetention": document["evidenceRetention"]})
    for position, row in enumerate(run["result"]["records"]):
        _url(row["sourceUrl"])
        if set(row) - {"sourceUrl", "types", "data", "truncated"}:
            _invalid()
        def inspect_structured(value):
            if type(value) is dict:
                if any(key in value for key in ("rawHtml", "html", "markdown")):
                    _invalid()
                for child in value.values():
                    inspect_structured(child)
            elif type(value) is list:
                for child in value:
                    inspect_structured(child)
        inspect_structured(row["data"])
        records.append({"sourceId": f"{expected_run_id}:structured:{position}", **row})
    if fallback_count:
        omissions.append(f"{fallback_count} source records have metadata only because the run explicitly reports their bodies were not retained.")
    if derived_count:
        omissions.append(f"{derived_count} job metadata records reference a page snapshot; they are not additional independently fetched job bodies.")
    if any(run["result"]["counts"][key] for key in ("frontierOmitted", "linksSkipped", "omittedRecords", "truncatedRecords")):
        omissions.append("The runtime reports omitted or truncated data; its recorded counts and diagnostics are preserved without reconstructing missing details.")
    if run["eventsDropped"]:
        omissions.append(f"The runtime dropped {run['eventsDropped']} events. Event logs are not included in the Research schema.")
    else:
        omissions.append("Runtime event logs are outside the Research schema and are not included.")

    candidates = []
    for slice_ in run["result"]["searchSlices"]:
        for row in slice_["results"]:
            candidates.append({"url": _url(row["url"]), "title": row["title"],
                               "source": f"discovery-unit:{slice_['unitId']}"})
    outcomes = [{"url": _url(unit["input"]["url"]), "status": unit["status"],
                 "sourceId": unit["id"], "reason": unit.get("error", "")}
                for unit in run["units"] if unit["kind"] == "page"]
    if len(records) > MAX_RECORDS or len(candidates) + len(outcomes) > MAX_TRACE:
        _large()
    title = run["input"].get("query") or f"Collider run {expected_run_id}"
    _text(title, 500, empty=False)
    bundle = {"manifest": {"schemaVersion": 1, "title": title, "omissions": omissions,
                            "warnings": [], "runSummary": summary},
              "files": {name: "".join(_json(row) + "\n" for row in rows) for name, rows in (
                  ("evidence.jsonl", records), ("candidates.jsonl", candidates),
                  ("outcomes.jsonl", outcomes), ("edges.jsonl", []))}}
    if len(_utf8(_json(bundle))) > MAX_REPORT_BYTES:
        _large()
    # Do not return references into the caller's mutable API response objects.
    return json.loads(_json(bundle))

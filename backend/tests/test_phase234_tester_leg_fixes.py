"""Phase 2-4 tester-leg fix locks (2026-08-07 post-tester-verdict).

Each test corresponds to a specific tester-found shortfall. If any of
these regresses, the corresponding item is broken again.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import pytest


# ============================================================
# FIX 2 · Origin resolver on /employers/connect
# ============================================================

def test_origin_resolver_greenhouse_board_extracts_token():
    from domains.supply.origin_resolver import resolve
    r = resolve("https://boards.greenhouse.io/somecompany")
    assert r["provider"] == "greenhouse"
    assert r["token"] == "somecompany"
    assert r["verdict"] == "verifiable_board"


def test_origin_resolver_lever_board_extracts_token():
    from domains.supply.origin_resolver import resolve
    r = resolve("https://jobs.lever.co/leveredhq")
    assert r["provider"] == "lever"
    assert r["token"] == "leveredhq"
    assert r["verdict"] == "verifiable_board"


def test_origin_resolver_ashby_board_extracts_token():
    from domains.supply.origin_resolver import resolve
    r = resolve("https://jobs.ashbyhq.com/OpenAI")
    assert r["provider"] == "ashby"
    assert r["token"].lower() == "openai"
    assert r["verdict"] == "verifiable_board"


def test_origin_resolver_workday_tenant_extracted():
    from domains.supply.origin_resolver import resolve
    r = resolve("https://acme.wd5.myworkdayjobs.com/External")
    assert r["provider"] == "workday"
    assert r["token"] == "acme"
    assert r["verdict"] == "verifiable_board"


def test_origin_resolver_example_com_is_unrecognized():
    """Founder directive: `example.com`-style URLs must NOT get a
    silent-pass with `status=pending`. They must land explicitly as
    `unrecognized_host`."""
    from domains.supply.origin_resolver import resolve
    r = resolve("https://example.com/careers")
    assert r["provider"] is None
    assert r["token"] is None
    assert r["verdict"] == "unrecognized_host"
    assert "long-tail" in r["note"] or "triage" in r["note"]


@pytest.mark.asyncio
async def test_connect_writes_unrecognized_host_status(monkeypatch):
    """Full-path integration: connect_employer with a non-board URL
    must set submission.status = "unrecognized_host" (NOT "pending").
    Anti-silent-scope guard."""
    from domains.supply import service as supply
    from unittest.mock import AsyncMock

    inserted = {}
    class _Subs:
        async def count_documents(self, *_a, **_kw): return 0
        async def find_one(self, *_a, **_kw): return None
        async def insert_one(self, doc): inserted.update(doc)
    class _AbuseLog:
        async def insert_one(self, doc): pass
    class _DB:
        employer_submissions = _Subs()
        supply_abuse_log = _AbuseLog()

    monkeypatch.setattr(supply, "get_db", lambda: _DB())
    monkeypatch.setattr(supply.audit, "write", AsyncMock())

    class _R: status_code = 200
    from domains.supply.service import ConnectRequest
    out = await supply.connect_employer(
        ConnectRequest(url="https://example.com/careers"),
        _R(),
        user={"id": "u-x"},
    )
    assert inserted.get("status") == "unrecognized_host"
    assert out["resolution"]["verdict"] == "unrecognized_host"
    assert out["submission"]["origin_resolution"]["provider"] is None


@pytest.mark.asyncio
async def test_connect_writes_pending_for_verifiable_board(monkeypatch):
    from domains.supply import service as supply
    from unittest.mock import AsyncMock

    inserted = {}
    class _Subs:
        async def count_documents(self, *_a, **_kw): return 0
        async def find_one(self, *_a, **_kw): return None
        async def insert_one(self, doc): inserted.update(doc)
    class _AbuseLog:
        async def insert_one(self, doc): pass
    class _DB:
        employer_submissions = _Subs()
        supply_abuse_log = _AbuseLog()
    monkeypatch.setattr(supply, "get_db", lambda: _DB())
    monkeypatch.setattr(supply.audit, "write", AsyncMock())

    class _R: status_code = 200
    from domains.supply.service import ConnectRequest
    out = await supply.connect_employer(
        ConnectRequest(url="https://boards.greenhouse.io/somecompany"),
        _R(),
        user={"id": "u-x"},
    )
    assert inserted.get("status") == "pending"
    assert out["resolution"]["provider"] == "greenhouse"
    assert out["resolution"]["token"] == "somecompany"


# ============================================================
# FIX 3 · Abuse logging on 429
# ============================================================

@pytest.mark.asyncio
async def test_connect_rate_limit_writes_abuse_row_and_audit(monkeypatch):
    """When the 24h cap trips, we MUST write a queryable row to
    `supply_abuse_log` AND emit an audit row under
    `supply.abuse.rate_limited`. Silent 429 is a rail violation."""
    from domains.supply import service as supply
    from fastapi import HTTPException

    abuse_rows: list = []
    audit_calls: list = []
    class _Subs:
        async def count_documents(self, *_a, **_kw): return supply._MAX_SUBMISSIONS_PER_24H
    class _AbuseLog:
        async def insert_one(self, doc): abuse_rows.append(doc)
    class _DB:
        employer_submissions = _Subs()
        supply_abuse_log = _AbuseLog()
    monkeypatch.setattr(supply, "get_db", lambda: _DB())
    async def _capture(*a, **kw): audit_calls.append((a, kw))
    monkeypatch.setattr(supply.audit, "write", _capture)

    class _R: status_code = 200
    from domains.supply.service import ConnectRequest
    with pytest.raises(HTTPException) as ei:
        await supply.connect_employer(
            ConnectRequest(url="https://boards.greenhouse.io/x"),
            _R(),
            user={"id": "u-x"},
        )
    assert ei.value.status_code == 429
    assert len(abuse_rows) == 1
    assert abuse_rows[0]["kind"] == "connect_rate_limit_exceeded"
    assert abuse_rows[0]["user_id"] == "u-x"
    # Audit trail: kind arg to audit.write must reference abuse.
    assert any("supply.abuse.rate_limited" in str(c[0]) for c in audit_calls), audit_calls


# ============================================================
# FIX 4 · Eligibility explain per-datum source + as_of
# ============================================================

@pytest.mark.asyncio
async def test_eligibility_explain_datum_carries_source_and_as_of(monkeypatch):
    from domains.eligibility import explain
    from datetime import datetime, timezone
    sealed = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _Coll:
        async def find_one(self, *_a, **_kw):
            return {"user_id": "u", "status": "ead_opt",
                    "opt_end": "2027-12-31",
                    "earliest_start": "2026-03-01",
                    "sealed_at": sealed,
                    "derived_flags": {"itar_excluded": True,
                                       "e_verify_need": True}}
    class _DB:
        eligibility_profiles = _Coll()
    monkeypatch.setattr(explain, "get_db", lambda: _DB())
    r = await explain.eligibility_explain(user={"id": "u"})
    known = r["known"]
    # status: user-self-attested + as_of == sealed_at.
    assert known["status"]["value"] == "ead_opt"
    assert known["status"]["source"] == "user_self_attested"
    assert known["status"]["as_of"] == sealed.isoformat()
    # opt_end and earliest_start MUST also carry labels.
    assert known["opt_end"]["source"] == "user_self_attested"
    assert known["earliest_start"]["source"] == "user_self_attested"
    assert known["opt_end"]["as_of"] == sealed.isoformat()
    # Derived flags: source=engine_derived, as_of=sealed_at.
    for k, v in known["derived_flags"].items():
        assert v["source"] == "engine_derived", (k, v)
        assert v["as_of"] == sealed.isoformat()


# ============================================================
# FIX 5 · Ghosting export explicit format handling
# ============================================================

@pytest.mark.asyncio
async def test_ghosting_pdf_returns_501_not_silent_json(monkeypatch):
    """?format=pdf MUST return HTTP 501 with `pdf_not_available` +
    capability field. Silent JSON on unknown format is a scope
    reduction and a rail violation."""
    from domains.exports import ghosting
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await ghosting.ghosting_evidence(format="pdf", user={"id": "u"})
    assert ei.value.status_code == 501
    assert ei.value.detail["error"] == "pdf_not_available"
    assert ei.value.detail["capability"]["formats_supported"] == ["json"]
    assert ei.value.detail["capability"]["formats_planned"] == ["pdf"]


@pytest.mark.asyncio
async def test_ghosting_capability_and_verification_in_success_response(monkeypatch):
    """The successful JSON response MUST include `capability` and
    `verification` blocks so consumers know supported formats + how
    to verify."""
    from domains.exports import ghosting

    class _Cursor:
        def __init__(self, docs): self._docs = list(docs)
        def __aiter__(self):
            async def gen():
                for d in self._docs: yield d
            return gen()
    class _AppsColl:
        def find(self, *_a, **_kw): return _Cursor([])
    class _OutColl:
        async def count_documents(self, *_a, **_kw): return 0
    class _DB:
        applications = _AppsColl()
        outcomes = _OutColl()
    monkeypatch.setattr(ghosting, "get_db", lambda: _DB())

    r = await ghosting.ghosting_evidence(format="json", user={"id": "u"})
    assert r["capability"]["formats_supported"] == ["json"]
    assert r["capability"]["formats_planned"] == ["pdf"]
    assert r["verification"]["algorithm"] == "HMAC-SHA256"
    assert "verify" in r["verification"]["verify_endpoint"]


# ============================================================
# FIX 6 · Signature verify endpoint
# ============================================================

@pytest.mark.asyncio
async def test_verify_endpoint_returns_true_for_valid_signature(monkeypatch):
    from domains.exports import ghosting
    monkeypatch.setenv("EVIDENCE_SIGNING_KEY", "test-key-42-abc")

    manifest = {"count": 0, "applications": [], "note": "empty"}
    canonical = json.dumps(manifest, sort_keys=True,
                             separators=(",", ":"), default=str).encode()
    sig = hmac.new(b"test-key-42-abc", canonical, hashlib.sha256).hexdigest()

    from domains.exports.ghosting import VerifyRequest
    out = await ghosting.ghosting_verify(
        VerifyRequest(manifest=manifest, signature=sig)
    )
    assert out["valid"] is True
    assert out["algorithm"] == "HMAC-SHA256"


@pytest.mark.asyncio
async def test_verify_endpoint_returns_false_for_forged_signature(monkeypatch):
    from domains.exports import ghosting
    monkeypatch.setenv("EVIDENCE_SIGNING_KEY", "test-key-42-abc")

    from domains.exports.ghosting import VerifyRequest
    out = await ghosting.ghosting_verify(
        VerifyRequest(
            manifest={"count": 0, "applications": []},
            signature="deadbeef" * 8,
        )
    )
    assert out["valid"] is False


@pytest.mark.asyncio
async def test_verify_endpoint_does_not_expose_signing_key(monkeypatch):
    """The verify endpoint MUST NOT surface the signing key in any of
    its response paths — anti-key-exposure lock."""
    from domains.exports import ghosting
    monkeypatch.setenv("EVIDENCE_SIGNING_KEY", "supersecret-signing-key-2026")
    from domains.exports.ghosting import VerifyRequest
    for good in (True, False):
        r = await ghosting.ghosting_verify(
            VerifyRequest(
                manifest={"count": 0, "applications": []},
                signature=("dead" * 16) if not good else "abc",
            )
        )
        blob = json.dumps(r)
        assert "supersecret-signing-key-2026" not in blob, blob

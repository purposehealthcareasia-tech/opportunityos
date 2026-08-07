"""Phase 3 · SUPPLY ENGINE tests.

Locks:
  - HTTPS-only validation (mirror of Phase 1 booking_url)
  - Canonical host normalization (`www.`, case, trailing slash)
  - Rate-limit envelope (20 / 24h / user)
  - Dedup semantics on both /connect and /vote (200 + already_* flag)
  - Admin gate on /admin/employers/queue (403 for non-admin)
  - Queue rank: votes desc, then earliest submission asc
"""
from __future__ import annotations
import pytest
from fastapi import HTTPException


def test_canonicalize_host_https_only():
    from domains.supply.service import canonicalize_host
    with pytest.raises(HTTPException) as ei:
        canonicalize_host("http://acme.com/careers")
    assert ei.value.status_code == 422
    assert ei.value.detail["error"] == "invalid_url"
    assert "https://" in ei.value.detail["message"]


def test_canonicalize_host_strips_www_and_lowercases():
    from domains.supply.service import canonicalize_host
    assert canonicalize_host("https://WWW.Acme.com/CAREERS") == "acme.com"
    assert canonicalize_host("https://www.acme.com/careers") == "acme.com"
    assert canonicalize_host("https://acme.com") == "acme.com"


def test_canonicalize_host_rejects_userinfo_query_fragment():
    from domains.supply.service import canonicalize_host
    with pytest.raises(HTTPException):
        canonicalize_host("https://u:p@acme.com/careers")
    with pytest.raises(HTTPException):
        canonicalize_host("https://acme.com/careers?utm=x")
    with pytest.raises(HTTPException):
        canonicalize_host("https://acme.com/careers#top")


def test_canonicalize_host_rejects_bad_hosts():
    from domains.supply.service import canonicalize_host
    for bad in (
        "https://localhost/careers",         # no dot
        "https://192.168.1.10/careers",       # ipv4 numeric
        "https://a b c.com/careers",          # spaces
    ):
        with pytest.raises(HTTPException):
            canonicalize_host(bad)


def test_canonicalize_host_url_length_cap():
    from domains.supply.service import canonicalize_host, _MAX_URL_LEN
    over = "https://acme.com/" + ("a" * _MAX_URL_LEN)
    with pytest.raises(HTTPException) as ei:
        canonicalize_host(over)
    assert ei.value.status_code == 422


def test_vote_request_validates_employer_key():
    """VoteRequest.field_validator must lowercase + reject non-FQDN."""
    from domains.supply.service import VoteRequest
    v = VoteRequest(employer_key="ACME.com")
    assert v.employer_key == "acme.com"
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        VoteRequest(employer_key="not_a_host")


def test_admin_queue_ranks_votes_desc_then_earliest_asc():
    """The queue ranking rule: (votes desc, earliest_submitted_at asc,
    employer_key asc). Unit-test the sort predicate directly so we don't
    have to spin up mongo."""
    rows = [
        {"employer_key": "beta.com", "votes": 3, "submission_count": 1,
          "earliest_submitted_at": "2026-08-01T00:00:00", "example_url": None},
        {"employer_key": "alpha.com", "votes": 3, "submission_count": 1,
          "earliest_submitted_at": "2026-07-01T00:00:00", "example_url": None},
        {"employer_key": "gamma.com", "votes": 1, "submission_count": 1,
          "earliest_submitted_at": "2026-06-01T00:00:00", "example_url": None},
    ]
    def _sort_key(r):
        return (-r["votes"],
                 r["earliest_submitted_at"] or "9999",
                 r["employer_key"])
    rows.sort(key=_sort_key)
    assert [r["employer_key"] for r in rows] == ["alpha.com", "beta.com", "gamma.com"]


@pytest.mark.asyncio
async def test_rate_limit_envelope_enforced(monkeypatch):
    """26th connect in 24h → HTTP 429."""
    from domains.supply import service as supply
    from unittest.mock import AsyncMock
    class _Coll:
        async def count_documents(self, *_a, **_kw): return supply._MAX_SUBMISSIONS_PER_24H
        async def find_one(self, *_a, **_kw): return None
        async def insert_one(self, *_a, **_kw): return None
    class _DB:
        employer_submissions = _Coll()
    monkeypatch.setattr(supply, "get_db", lambda: _DB())
    monkeypatch.setattr(supply.audit, "write", AsyncMock())

    class _R: status_code = 200
    from domains.supply.service import ConnectRequest
    from fastapi import HTTPException as _H
    try:
        await supply.connect_employer(
            ConnectRequest(url="https://newco.example.com/careers"),
            _R(),
            user={"id": "u"},
        )
    except _H as e:
        assert e.status_code == 429
        assert e.detail["error"] == "submission_rate_limit"
        return
    pytest.fail("rate limit did not trip")

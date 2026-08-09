"""Phase 5a · Passport Share Link — regression tests.

Uses monkeypatched motor collections to keep test-runs deterministic
(same pattern as tests/test_phase234_tester_leg_fixes.py). Real
end-to-end flow is separately verified via curl on the preview host.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException


# -------- helpers ---------------------------------------------------
class _FakeUpdateResult:
    def __init__(self, matched: int = 0):
        self.matched_count = matched


class _FakeShareColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, q, projection=None):
        for d in self.docs:
            ok = all(k == "revoked_at" or d.get(k) == v for k, v in q.items())
            # Handle revoked_at: None filter
            if "revoked_at" in q:
                if q["revoked_at"] is None and d.get("revoked_at") is not None:
                    ok = False
            if ok:
                return d
        return None

    async def insert_one(self, d): self.docs.append(d); return None

    async def update_one(self, q, upd):
        for d in self.docs:
            match = all(k == "revoked_at" or d.get(k) == v for k, v in q.items())
            if "revoked_at" in q and q["revoked_at"] is None and d.get("revoked_at") is not None:
                match = False
            if match:
                if "$set" in upd:
                    d.update(upd["$set"])
                if "$inc" in upd:
                    for k, v in upd["$inc"].items():
                        d[k] = int(d.get(k) or 0) + v
                return _FakeUpdateResult(matched=1)
        return _FakeUpdateResult(matched=0)


class _FakeClaimsCursor:
    def __init__(self, docs): self._docs = docs
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _FakeClaims:
    def __init__(self, docs): self.docs = docs
    def find(self, *_a, **_kw): return _FakeClaimsCursor(self.docs)


class _FakeUsersColl:
    def __init__(self, d): self.d = d
    async def find_one(self, *_a, **_kw): return self.d


class _FakeELP:
    def __init__(self, d): self.d = d
    async def find_one(self, *_a, **_kw): return self.d


class _FakeViewReceipts:
    def __init__(self): self.docs = []
    async def insert_one(self, d): self.docs.append(d)
    def find(self, *_a, **_kw): return _FakeClaimsCursor(self.docs)


class _FakeDB:
    def __init__(self, shares, users, elp, claims):
        self.passport_shares = _FakeShareColl(shares)
        self.users = _FakeUsersColl(users)
        self.eligibility_profiles = _FakeELP(elp)
        self.claims = _FakeClaims(claims)
        self.share_view_receipts = _FakeViewReceipts()


class _FakeReq:
    def __init__(self):
        self.headers = {"x-forwarded-for": "203.0.113.42", "user-agent": "pytest/1.0"}
        self.client = type("_c", (), {"host": "203.0.113.42"})()


# ==================================================================
# Signature + scope filter
# ==================================================================
def test_sign_share_stable_across_calls():
    from domains.share.service import _sign_share
    a = _sign_share("s1", "u1", "moderate", "2026-08-09T00:00:00+00:00")
    b = _sign_share("s1", "u1", "moderate", "2026-08-09T00:00:00+00:00")
    assert a == b and len(a) == 64


def test_sign_share_changes_when_scope_changes():
    from domains.share.service import _sign_share
    a = _sign_share("s1", "u1", "moderate", "2026-08-09T00:00:00+00:00")
    b = _sign_share("s1", "u1", "full",     "2026-08-09T00:00:00+00:00")
    assert a != b


def test_redact_ip_ipv4_to_24():
    from domains.share.service import _redact_ip
    assert _redact_ip("203.0.113.42").endswith("/24")
    assert _redact_ip("nope") == "unknown"


# ==================================================================
# create + revoke + list flow (auth path)
# ==================================================================
@pytest.mark.asyncio
async def test_create_share_returns_signed_url_and_persists_row(monkeypatch):
    from domains.share import service as share
    from domains.share.service import CreateShareRequest
    fake = _FakeDB(
        shares=[], users={"id": "u1", "name": "Test User"},
        elp={"user_id": "u1", "status": "us_citizen"},
        claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    out = await share.create_share(
        CreateShareRequest(scope="moderate", ttl_hours=24, employer_hint="Lucid"),
        user={"id": "u1"},
    )
    assert out["share_id"]
    assert out["public_path"].startswith("/api/v1/share/p/")
    assert "?t=" in out["public_path"]
    assert out["scope"] == "moderate"
    assert out["revocable"] is True
    assert out["receipted"] is True
    assert len(fake.passport_shares.docs) == 1
    assert fake.passport_shares.docs[0]["employer_hint"] == "Lucid"
    assert fake.passport_shares.docs[0]["revoked_at"] is None


@pytest.mark.asyncio
async def test_create_share_rejects_bad_scope(monkeypatch):
    from domains.share import service as share
    from domains.share.service import CreateShareRequest
    fake = _FakeDB([], {}, {}, [])
    monkeypatch.setattr(share, "get_db", lambda: fake)
    with pytest.raises(HTTPException) as ei:
        await share.create_share(
            CreateShareRequest(scope="private_dm", ttl_hours=24),
            user={"id": "u1"},
        )
    assert ei.value.status_code == 400
    assert ei.value.detail == "bad_scope"


@pytest.mark.asyncio
async def test_revoke_share_marks_revoked_immediately(monkeypatch):
    from domains.share import service as share
    fake = _FakeDB(
        shares=[{"id": "s1", "user_id": "u1", "revoked_at": None}],
        users={}, elp={}, claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    out = await share.revoke_share(share_id="s1", user={"id": "u1"})
    assert out["revoked"] is True
    assert fake.passport_shares.docs[0]["revoked_at"] is not None


@pytest.mark.asyncio
async def test_revoke_share_404_when_owner_mismatch(monkeypatch):
    from domains.share import service as share
    fake = _FakeDB(
        shares=[{"id": "s1", "user_id": "OWNER", "revoked_at": None}],
        users={}, elp={}, claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    with pytest.raises(HTTPException) as ei:
        await share.revoke_share(share_id="s1", user={"id": "attacker"})
    assert ei.value.status_code == 404


# ==================================================================
# public GET path (signature + filter + receipt)
# ==================================================================
@pytest.mark.asyncio
async def test_public_view_valid_signature_returns_filtered_and_receipts(monkeypatch):
    from domains.share import service as share
    from domains.share.service import _sign_share
    from datetime import datetime, timedelta, timezone

    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    sig = _sign_share("share-A", "u1", "moderate", exp)
    fake = _FakeDB(
        shares=[{
            "id": "share-A", "user_id": "u1", "scope": "moderate",
            "expires_at": exp, "revoked_at": None,
        }],
        users={"id": "u1", "name": "Alice"},
        elp={"user_id": "u1", "status": "us_citizen"},
        claims=[
            {"user_id": "u1", "state": "approved", "kind": "education",
             "data": {"school": "State U", "degree": "BSc", "field": "CS", "graduation_year": 2018}},
            {"user_id": "u1", "state": "approved", "kind": "employment",
             "data": {"title": "Eng", "company": "Acme", "start_year": 2019, "end_year": 2023}},
        ],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)

    out = await share.public_view(_FakeReq(), share_id="share-A", t=sig)
    assert out["share_id"] == "share-A"
    assert out["scope"] == "moderate"
    # moderate scope: name + education + us_work_authorized
    assert out["passport"]["name"] == "Alice"
    assert out["passport"]["us_work_authorized"] is True
    assert len(out["passport"]["education"]) == 1
    # employment history NOT surfaced under moderate
    assert "employment_history" not in out["passport"]
    # receipt row present
    assert len(fake.share_view_receipts.docs) == 1
    r = fake.share_view_receipts.docs[0]
    assert r["ip_network"].endswith("/24")
    # ua_hash is a short SHA-256 prefix, not the raw UA
    assert len(r["ua_hash"]) == 16 and "pytest" not in r["ua_hash"]


@pytest.mark.asyncio
async def test_public_view_full_scope_includes_employment_and_skills(monkeypatch):
    from domains.share import service as share
    from domains.share.service import _sign_share
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    sig = _sign_share("share-F", "u2", "full", exp)
    fake = _FakeDB(
        shares=[{"id": "share-F", "user_id": "u2", "scope": "full",
                 "expires_at": exp, "revoked_at": None}],
        users={"id": "u2", "name": "Bob"},
        elp={"user_id": "u2", "status": "ead_opt"},
        claims=[
            {"user_id": "u2", "state": "approved", "kind": "employment",
             "data": {"title": "SWE", "company": "Beta", "start_year": 2020, "end_year": 2024}},
            {"user_id": "u2", "state": "approved", "kind": "skill",
             "data": {"name": "python"}},
            {"user_id": "u2", "state": "approved", "kind": "skill",
             "data": {"name": "rust"}},
        ],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    out = await share.public_view(_FakeReq(), share_id="share-F", t=sig)
    assert out["passport"]["employment_history"] == [
        {"title": "SWE", "company": "Beta", "start_year": 2020, "end_year": 2024}
    ]
    assert out["passport"]["top_skills"] == ["python", "rust"]
    # ead_opt is NOT us_citizen/permanent_resident → us_work_authorized False.
    # Rails: we surface a boolean only, never the visa literal.
    assert out["passport"]["us_work_authorized"] is False


@pytest.mark.asyncio
async def test_public_view_minimum_scope_only_name(monkeypatch):
    from domains.share import service as share
    from domains.share.service import _sign_share
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    sig = _sign_share("share-M", "u3", "minimum", exp)
    fake = _FakeDB(
        shares=[{"id": "share-M", "user_id": "u3", "scope": "minimum",
                 "expires_at": exp, "revoked_at": None}],
        users={"id": "u3", "name": "Chi"}, elp={}, claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    out = await share.public_view(_FakeReq(), share_id="share-M", t=sig)
    assert set(out["passport"].keys()) == {"name"}
    assert out["passport"]["name"] == "Chi"


@pytest.mark.asyncio
async def test_public_view_bad_signature_403(monkeypatch):
    from domains.share import service as share
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    fake = _FakeDB(
        shares=[{"id": "s", "user_id": "u", "scope": "moderate",
                 "expires_at": exp, "revoked_at": None}],
        users={}, elp={}, claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    with pytest.raises(HTTPException) as ei:
        await share.public_view(_FakeReq(), share_id="s", t="a" * 64)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_public_view_expired_410(monkeypatch):
    from domains.share import service as share
    from domains.share.service import _sign_share
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sig = _sign_share("s", "u", "moderate", exp)
    fake = _FakeDB(
        shares=[{"id": "s", "user_id": "u", "scope": "moderate",
                 "expires_at": exp, "revoked_at": None}],
        users={}, elp={}, claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    with pytest.raises(HTTPException) as ei:
        await share.public_view(_FakeReq(), share_id="s", t=sig)
    assert ei.value.status_code == 410
    assert ei.value.detail == "share_expired"


@pytest.mark.asyncio
async def test_public_view_revoked_410_takes_precedence_over_signature(monkeypatch):
    """Revocation MUST be checked BEFORE signature — a compromised link
    stops working the moment the owner clicks revoke, even if the
    signature is otherwise valid."""
    from domains.share import service as share
    from domains.share.service import _sign_share
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    sig = _sign_share("s", "u", "moderate", exp)
    fake = _FakeDB(
        shares=[{"id": "s", "user_id": "u", "scope": "moderate",
                 "expires_at": exp, "revoked_at": datetime.now(timezone.utc).isoformat()}],
        users={}, elp={}, claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    with pytest.raises(HTTPException) as ei:
        await share.public_view(_FakeReq(), share_id="s", t=sig)
    assert ei.value.status_code == 410
    assert ei.value.detail == "share_revoked"


@pytest.mark.asyncio
async def test_public_view_never_leaks_sealed_or_itar_fields(monkeypatch):
    """The filtered payload MUST NOT contain sealed claim data, ITAR
    flags, private preferences, or salary. `full` scope is the widest
    surface — this test locks the shape."""
    from domains.share import service as share
    from domains.share.service import _sign_share, _SCOPES
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    sig = _sign_share("s", "u", "full", exp)
    fake = _FakeDB(
        shares=[{"id": "s", "user_id": "u", "scope": "full",
                 "expires_at": exp, "revoked_at": None}],
        users={"id": "u", "name": "X", "salary_history": ["never surface"]},
        elp={"user_id": "u", "status": "us_citizen", "itar_cleared": True},
        claims=[],
    )
    monkeypatch.setattr(share, "get_db", lambda: fake)
    out = await share.public_view(_FakeReq(), share_id="s", t=sig)
    forbidden = {"itar", "salary", "sealed", "preferences", "visa"}
    body = str(out["passport"]).lower()
    for f in forbidden:
        assert f not in body, f"leak: {f} appeared in filtered payload"
    # Widest scope shape lock.
    allowed_keys = _SCOPES["full"]
    assert set(out["passport"].keys()) <= allowed_keys

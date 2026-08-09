"""Phase 5g/h/i/j — batch regression tests."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from fastapi import HTTPException


class _Cursor:
    def __init__(self, docs): self._docs = list(docs)
    def sort(self, *_a, **_kw): return self
    def limit(self, *_a, **_kw): return self
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _Coll:
    def __init__(self, docs=None): self.docs = list(docs or [])
    async def find_one(self, q, projection=None):
        for d in self.docs:
            if _matches(d, q):
                return d
        return None
    def find(self, q, projection=None):
        return _Cursor([d for d in self.docs if _matches(d, q)])
    async def count_documents(self, q):
        return sum(1 for d in self.docs if _matches(d, q))
    async def insert_one(self, d):
        self.docs.append(d)
    async def update_one(self, q, upd):
        for d in self.docs:
            if _matches(d, q):
                if "$set" in upd: d.update(upd["$set"])
                if "$inc" in upd:
                    for k, v in upd["$inc"].items():
                        d[k] = int(d.get(k) or 0) + v
                return type("R", (), {"matched_count": 1})()
        return type("R", (), {"matched_count": 0})()
    def aggregate(self, pipeline):
        # Minimal $group+$sum+$match implementation used only by 5j.
        if not pipeline: return _Cursor([])
        group = next((s for s in pipeline if "$group" in s), None)
        match = next((s for s in pipeline if "$match" in s), None)
        if not group: return _Cursor([])
        key_expr = group["$group"]["_id"]  # e.g. "$status"
        field = key_expr.lstrip("$")
        counts: dict = {}
        for d in self.docs:
            k = d.get(field)
            counts[k] = counts.get(k, 0) + 1
        rows = [{"_id": k, "n": n} for k, n in counts.items()]
        if match:
            m = match["$match"]
            def _ok(r):
                for k, v in m.items():
                    if isinstance(v, dict) and "$gte" in v:
                        if not (r.get(k) is not None and r[k] >= v["$gte"]):
                            return False
                    elif r.get(k) != v:
                        return False
                return True
            rows = [r for r in rows if _ok(r)]
        return _Cursor(rows)


def _matches(d, q):
    for k, v in q.items():
        if isinstance(v, dict):
            if "$in" in v and d.get(k) not in v["$in"]:
                return False
            if "$gte" in v:
                if d.get(k) is None or d.get(k) < v["$gte"]:
                    return False
            if "$ne" in v and d.get(k) == v["$ne"]:
                return False
            if "$type" in v:
                # only "number" used
                if not isinstance(d.get(k), (int, float)):
                    return False
        else:
            if d.get(k) != v:
                return False
    return True


class _DB:
    def __init__(self, **kw):
        for coll_name, docs in kw.items():
            setattr(self, coll_name, _Coll(docs))


class _FakeReq:
    def __init__(self):
        self.headers = {"x-forwarded-for": "203.0.113.42", "user-agent": "pytest/1.0"}
        self.client = type("_c", (), {"host": "203.0.113.42"})()


# =========================================================== 5g Employer Dashboard
@pytest.mark.asyncio
async def test_employer_dashboard_requires_verified_membership(monkeypatch):
    from domains.employer_dashboard import service as ed
    db = _DB(employer_memberships=[])
    monkeypatch.setattr(ed, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await ed.summary(user={"id": "u1"})
    assert ei.value.status_code == 403
    assert ei.value.detail["error"] == "employer_membership_required"


@pytest.mark.asyncio
async def test_employer_dashboard_summary_own_data_only(monkeypatch):
    from domains.employer_dashboard import service as ed
    db = _DB(
        employer_memberships=[
            {"user_id": "u1", "employer_canonical_key": "acme", "verified": True},
        ],
        applications=[
            {"id": "a1", "employer_canonical_key": "acme", "score": 82},
            {"id": "a2", "employer_canonical_key": "acme", "score": 40},
        ],
        application_outcomes=[
            {"employer_canonical_key": "acme", "event": "response_received", "lag_days": 3},
        ],
    )
    monkeypatch.setattr(ed, "get_db", lambda: db)
    out = await ed.summary(user={"id": "u1"})
    assert out["employer_canonical_key"] == "acme"
    assert out["total_applications"] == 2
    assert out["responded_count"] == 1
    assert out["response_rate"] == 0.5
    assert out["median_days_to_response"] == 3
    assert out["application_quality_pass_rate"] == 0.5
    assert out["rank_bucket"] is None  # single-employer owner → no rank
    assert out["rank_scope"] == "not_available"
    assert out["cross_employer_disclosure"] is False


# =========================================================== 5h Layoff-Day
@pytest.mark.asyncio
async def test_layoff_day_orchestrate_composes_components(monkeypatch):
    from domains.layoff_day import service as ld
    db = _DB(
        preferences=[{"user_id": "u1", "roles": ["swe"], "locations": ["SF"], "remote_ok": True}],
        eligibility_profiles=[{"user_id": "u1", "status": "us_citizen",
                                 "created_at": "2026-08-01T00:00:00+00:00"}],
        jobs=[{"status": "live"}] * 42,
    )
    monkeypatch.setattr(ld, "get_db", lambda: db)
    out = await ld.orchestrate(user={"id": "u1"})
    c = out["components"]
    assert c["broad_spectrum"]["available"] is True
    assert c["broad_spectrum"]["remote_ok"] is True
    assert c["eligibility_summary"]["available"] is True
    assert c["eligibility_summary"]["status"] == "us_citizen"
    assert c["wave_preview"]["live_jobs_count"] == 42
    assert c["followup_preset"]["dispatch_mode"] == "dry_run"
    assert out["consent_gates_intact"] is True
    assert out["income_promises"] is None
    # Copy rule: no income promise strings.
    body = str(out).lower()
    for banned in ("guaranteed income", "guarantee salary", "salary guarantee"):
        assert banned not in body


@pytest.mark.asyncio
async def test_layoff_day_honest_no_eligibility(monkeypatch):
    from domains.layoff_day import service as ld
    db = _DB(preferences=[{"user_id": "u1"}], eligibility_profiles=[], jobs=[])
    monkeypatch.setattr(ld, "get_db", lambda: db)
    out = await ld.orchestrate(user={"id": "u1"})
    assert out["components"]["eligibility_summary"]["available"] is False
    assert out["components"]["eligibility_summary"]["reason"] == "no_eligibility_profile"


# =========================================================== 5i Passport-as-API
@pytest.mark.asyncio
async def test_passport_api_mint_returns_token_once_and_stores_only_hash(monkeypatch):
    from domains.passport_api import service as pa
    from domains.passport_api.service import MintTokenRequest
    db = _DB(passport_api_tokens=[])
    monkeypatch.setattr(pa, "get_db", lambda: db)
    out = await pa.mint_token(
        MintTokenRequest(scope="moderate", ttl_hours=24, audience_label="Acme HR"),
        user={"id": "u1"},
    )
    tok = out["token"]
    assert len(tok) >= 30  # ~43 chars actual
    # Row stored ONLY the hash, never the plain token
    row = db.passport_api_tokens.docs[0]
    assert "token" not in row
    assert row["token_hash"] == pa._hash_token(tok)
    assert row["revoked_at"] is None


@pytest.mark.asyncio
async def test_passport_api_bad_scope_400(monkeypatch):
    from domains.passport_api import service as pa
    from domains.passport_api.service import MintTokenRequest
    db = _DB(passport_api_tokens=[])
    monkeypatch.setattr(pa, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await pa.mint_token(
            MintTokenRequest(scope="rogue", ttl_hours=24),
            user={"id": "u1"},
        )
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_passport_api_access_filters_by_scope_and_receipts(monkeypatch):
    from domains.passport_api import service as pa
    from domains.share import service as share
    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    plain = "sample-token-xyz-0001"
    tok_hash = pa._hash_token(plain)
    db = _DB(
        passport_api_tokens=[{
            "id": "tid-1", "user_id": "u1", "scope": "minimum",
            "token_hash": tok_hash, "expires_at": exp,
            "revoked_at": None, "access_count": 0,
        }],
        passport_api_receipts=[],
    )
    # Share service._load_filtered_passport uses its own db — monkeypatch that too.
    share_db = type("_S", (), {
        "users": type("_U", (), {"find_one": staticmethod(lambda *a, **k: _async_return({"id": "u1", "name": "X"}))})(),
        "eligibility_profiles": type("_E", (), {"find_one": staticmethod(lambda *a, **k: _async_return({"user_id": "u1", "status": "us_citizen"}))})(),
        "claims": type("_C", (), {"find": staticmethod(lambda *a, **k: _Cursor([]))})(),
    })()
    monkeypatch.setattr(pa, "get_db", lambda: db)
    monkeypatch.setattr(share, "get_db", lambda: share_db)
    out = await pa.passport_via_token(_FakeReq(), authorization=f"Bearer {plain}")
    assert out["scope"] == "minimum"
    assert set(out["passport"].keys()) == {"name"}
    # Receipt written + access_count incremented
    assert len(db.passport_api_receipts.docs) == 1
    row = db.passport_api_tokens.docs[0]
    assert row["access_count"] == 1


def _async_return(v):
    async def _a(*_a, **_kw): return v
    return _a()


@pytest.mark.asyncio
async def test_passport_api_revoked_token_410(monkeypatch):
    from domains.passport_api import service as pa
    plain = "revoked-token-xxxx"
    tok_hash = pa._hash_token(plain)
    now = datetime.now(timezone.utc).isoformat()
    db = _DB(passport_api_tokens=[{
        "id": "tid-1", "user_id": "u1", "scope": "minimum",
        "token_hash": tok_hash, "expires_at": now, "revoked_at": now,
        "access_count": 0,
    }])
    monkeypatch.setattr(pa, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await pa.passport_via_token(_FakeReq(), authorization=f"Bearer {plain}")
    assert ei.value.status_code == 410
    assert ei.value.detail == "token_revoked"


@pytest.mark.asyncio
async def test_passport_api_missing_bearer_401(monkeypatch):
    from domains.passport_api import service as pa
    db = _DB(passport_api_tokens=[])
    monkeypatch.setattr(pa, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await pa.passport_via_token(_FakeReq(), authorization=None)
    assert ei.value.status_code == 401


# =========================================================== 5j Cohort Intel
@pytest.mark.asyncio
async def test_cohort_intel_empty_state_when_below_threshold(monkeypatch):
    from domains.cohort_intel import service as ci
    db = _DB(users=[{"id": f"u{i}"} for i in range(10)],
              applications=[], eligibility_profiles=[])
    monkeypatch.setattr(ci, "get_db", lambda: db)
    out = await ci.summary(user={"id": "u0"})
    assert out["data_available"] is False
    assert out["current_pool_size"] == 10
    assert out["min_pool_size"] == 50
    assert out["buckets"] == []
    assert "invent numbers" in out["notice"].lower()


@pytest.mark.asyncio
async def test_cohort_intel_reveals_only_k_anonymous_buckets(monkeypatch):
    from domains.cohort_intel import service as ci
    users = [{"id": f"u{i}"} for i in range(80)]
    apps = [{"id": f"a{i}"} for i in range(200)]
    # Two dense buckets + one thin (5 members) that must be omitted.
    profiles = (
        [{"user_id": f"u{i}", "status": "us_citizen"} for i in range(40)]
        + [{"user_id": f"u{i+40}", "status": "ead_opt"} for i in range(35)]
        + [{"user_id": f"u{i+75}", "status": "sponsorship_needed"} for i in range(5)]
    )
    db = _DB(users=users, applications=apps, eligibility_profiles=profiles)
    monkeypatch.setattr(ci, "get_db", lambda: db)
    out = await ci.summary(user={"id": "u0"})
    assert out["data_available"] is True
    assert out["current_pool_size"] == 80
    assert out["total_applications"] == 200
    kinds = [b["eligibility_class"] for b in out["buckets"]]
    assert "us_citizen" in kinds
    assert "ead_opt" in kinds
    # 5 members in sponsorship_needed → below 10 → omitted (k-anonymity)
    assert "sponsorship_needed" not in kinds

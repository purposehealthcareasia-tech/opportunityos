"""Phase 1 §v (1b) — Standing Wave AAB tick regression tests.

These tests lock the CAP-INVARIANT of `run_standing_waves_after_aab_tick`
using pure unit-level mocking of the DB / repository / cap-check layers,
so the tests are hermetic to motor/pytest-asyncio event-loop issues.

Behavior locked:
  * new spectrum-matching job → shortlisted (queued=1)
  * cap-exceeded job → NOT shortlisted (queued=0), blocked reason recorded
  * inactive Standing Wave row → skipped
  * wave_authorizations row written on every user processed, with
    consent-scope snapshot + `triggered_by == "standing_wave_aab_tick"`
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


NOW = datetime.now(timezone.utc)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
    async def __aiter__(self):
        for d in self._docs:
            yield d
    async def to_list(self, length=None):
        return list(self._docs)
    def sort(self, *_a, **_kw): return self
    def limit(self, *_a, **_kw): return self


class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted = []
    async def find_one(self, q=None, *_a, **_kw):
        q = q or {}
        for r in self.rows:
            if all(r.get(k) == v for k, v in q.items()):
                return dict(r)
        return None
    def find(self, q=None, *_a, **_kw):
        q = q or {}
        return _FakeCursor([r for r in self.rows if all(r.get(k) == v for k, v in q.items())])
    async def insert_one(self, doc):
        self.inserted.append(dict(doc))
        self.rows.append(dict(doc))
    async def count_documents(self, q=None):
        q = q or {}
        return sum(1 for r in self.rows if all(r.get(k) == v for k, v in q.items()))


class _FakeDB:
    def __init__(self):
        self.standing_waves = _FakeCollection()
        self.consent_records = _FakeCollection()
        self.applications = _FakeCollection()
        self.wave_authorizations = _FakeCollection()
        self.audit_logs = _FakeCollection()


@pytest.mark.asyncio
async def test_standing_wave_tick_full_flow(monkeypatch):
    """Three sub-assertions collapsed into one test:
      A) matching arrival for user with active Standing Wave → queued
      B) cap-blocked arrival → NOT queued, blocked reason recorded
      C) user with active=False → skipped
    Uses fully-mocked DB + gate_engine + cap_svc so the test is hermetic.
    """
    fake_db = _FakeDB()

    # ------ Users + Standing Wave rows ------ #
    user_a = f"user-a-{uuid.uuid4().hex[:8]}"
    user_b = f"user-b-{uuid.uuid4().hex[:8]}"
    user_c = f"user-c-{uuid.uuid4().hex[:8]}"
    fake_db.standing_waves.rows.extend([
        {"user_id": user_a, "active": True,
          "scope": {"cap": 10, "standing_wave": True}, "created_at": NOW},
        {"user_id": user_b, "active": True,
          "scope": {"cap": 10, "standing_wave": True}, "created_at": NOW},
        {"user_id": user_c, "active": False,
          "scope": {"cap": 10, "standing_wave": True}, "created_at": NOW},
    ])
    for u in (user_a, user_b):
        fake_db.consent_records.rows.append({
            "id": f"c-{u}", "user_id": u, "scope": "submit_applications",
            "status": "granted", "granted_at": NOW,
        })

    # ------ One new arriving job ------ #
    new_job_id = f"job-{uuid.uuid4().hex[:8]}"
    new_job = {
        "id": new_job_id, "canonical_key": "acme::new-role",
        "title": "Role Fresh", "company_name": "Acme",
        "company_domain": "acme.io",
        "status": "live", "last_verified": NOW,
        "eligibility_requirements": {}, "requirements": {},
        "is_sample": False, "lane": "career", "first_seen": NOW,
    }

    # ------ Monkey-patches ------ #
    from core import db as core_db
    monkeypatch.setattr(core_db, "get_db", lambda: fake_db)
    monkeypatch.setattr(core_db, "_db", fake_db)

    # jobs_repo.list_live returns our one new job
    from domains.jobs import repository as jobs_repo
    async def _list_live():
        return [new_job]
    monkeypatch.setattr(jobs_repo, "list_live", _list_live)

    # gate_engine.build_context returns an empty user context (no
    # existing apps, no hidden ids); gate_engine.evaluate says pass-all
    # for any job (so scope + cap are the only gates that matter).
    from services import gate_engine
    async def _build_ctx(user_id):
        return {
            "user_id": user_id,
            "existing_applications": set(),
            "hidden_job_ids": set(),
            "preferences": {}, "eligibility": {},
            "approved_skills": set(),
            "approved_education": [], "approved_employment": [],
            "approved_certifications": [],
        }
    monkeypatch.setattr(gate_engine, "build_context", _build_ctx)
    monkeypatch.setattr(gate_engine, "evaluate", lambda ctx, job: {
        "pass_all": True, "fail_reasons": [], "unknown_reasons": [],
        "gates": {}, "notes": [],
    })

    # cap_svc.check_cap: user_a has room (ok=True remaining=10);
    # user_b is capped (ok=False remaining=0)
    from services import employer_cap as cap_svc
    async def _check_cap(user_id, job):
        if user_id == user_b:
            return {"ok": False, "employer": "cn:acme",
                     "current": 3, "cap": 3, "remaining": 0,
                     "window_days": 30}
        return {"ok": True, "employer": "cn:acme",
                 "current": 0, "cap": 3, "remaining": 10,
                 "window_days": 30}
    monkeypatch.setattr(cap_svc, "check_cap", _check_cap)

    # apps_svc.shortlist just appends to applications and returns a row
    from domains.applications import service as apps_svc
    async def _shortlist(user_id, job):
        row = {"id": str(uuid.uuid4()), "user_id": user_id,
                "job_id": job["id"], "state": "shortlisted"}
        fake_db.applications.rows.append(dict(row))
        fake_db.applications.inserted.append(dict(row))
        return row
    monkeypatch.setattr(apps_svc, "shortlist", _shortlist)

    # audit.write no-op (already writes to fake_db.audit_logs anyway)
    from domains.audit import service as audit_svc
    async def _audit_write(actor, action, ref, meta): pass
    monkeypatch.setattr(audit_svc, "write", _audit_write)

    # ---------- RUN THE SUT ---------- #
    # Also monkey-patch the wave module's local `get_db` reference —
    # imported directly via `from core.db import get_db`, so setattr on
    # `core.db.get_db` isn't sufficient when a prior test has already
    # triggered lazy initialization of `core.db._db` (Motor bound to a
    # now-closed event loop). Monkeypatching the module's local binding
    # forces the SUT through our fake DB directly.
    import domains.wave as _wave_mod
    monkeypatch.setattr(_wave_mod, "get_db", lambda: fake_db)

    from domains.wave import run_standing_waves_after_aab_tick
    summary = await run_standing_waves_after_aab_tick([new_job_id])

    # ---------- ASSERTIONS ---------- #
    assert summary["users_processed"] == 2, summary
    assert summary["queued_total"] == 1, summary

    # A queued
    a_apps = [r for r in fake_db.applications.rows if r["user_id"] == user_a]
    assert len(a_apps) == 1
    row_a = next((r for r in fake_db.wave_authorizations.rows if r["user_id"] == user_a), None)
    assert row_a is not None
    assert row_a["triggered_by"] == "standing_wave_aab_tick"
    assert row_a["queued_count"] == 1
    assert row_a["consents_snapshot"]["submit_applications"] == "granted"

    # B blocked (cap)
    b_apps = [r for r in fake_db.applications.rows if r["user_id"] == user_b]
    assert len(b_apps) == 0
    row_b = next((r for r in fake_db.wave_authorizations.rows if r["user_id"] == user_b), None)
    assert row_b is not None
    assert row_b["triggered_by"] == "standing_wave_aab_tick"
    assert row_b["queued_count"] == 0
    assert row_b["breakdown"]["blocked_cap"] >= 1, row_b["breakdown"]

    # C skipped
    c_rows = [r for r in fake_db.wave_authorizations.rows if r["user_id"] == user_c]
    assert c_rows == []

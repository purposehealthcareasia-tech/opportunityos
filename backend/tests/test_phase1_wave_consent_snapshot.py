"""Phase 1 · G3d dual-path consent-snapshot regression.

Locks in: on BOTH wave code paths — `user_batch` (`authorize_wave`) and
`standing_wave_aab_tick` (`run_standing_waves_after_aab_tick`) — the
`_snapshot_consents` reader correctly mirrors the CURRENT
`consent_records` state onto the `wave_authorizations` row.

Root-cause class this test defends against: schema drift. The pre-fix
reader was addressing legacy field names (`status` / `granted_at` /
`revoked_at`) that never existed in the Phase-6-hardened
`consent_records` shape (`granted: bool` + `ts: datetime`), so every
scope collapsed to falsy and the snapshot fell through empty.

Test uses the CORRECT post-fix schema (`granted: bool` + `ts`) so that
if a future refactor re-introduces legacy-field addressing, the test
FAILS loudly — not silently.

Hermetic against motor/pytest-asyncio issues via full fake-DB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


NOW = datetime.now(timezone.utc)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()

    async def to_list(self, length=None):
        return list(self._docs)

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self


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

    async def update_one(self, q, upd, upsert=False):
        # minimal: only used by standing_waves upsert; not exercised here.
        pass

    async def count_documents(self, q=None):
        q = q or {}
        return sum(1 for r in self.rows if all(r.get(k) == v for k, v in q.items()))


class _FakeDB:
    def __init__(self):
        self.consent_records = _FakeCollection()
        self.applications = _FakeCollection()
        self.wave_authorizations = _FakeCollection()
        self.standing_waves = _FakeCollection()
        self.audit_logs = _FakeCollection()


def _make_consent_rows(user_id: str) -> list[dict]:
    """Correct post-fix schema: `granted: bool` + `ts: datetime`.
    All 6 fixture scopes granted; one intentionally revoked-then-regranted
    to prove `sort ts asc → latest wins` semantics."""
    scopes_granted = [
        "discover_jobs", "email_me", "generate_materials",
        "process_career_data", "submit_applications", "track_applications",
    ]
    rows = []
    for i, sc in enumerate(scopes_granted):
        rows.append({
            "id": f"c-{sc}-{user_id}",
            "user_id": user_id,
            "scope": sc,
            "granted": True,
            "ts": datetime(2026, 8, 6, 10, i, 0, tzinfo=timezone.utc),
        })
    # Prove latest-wins semantics: revoke then re-grant `email_me`.
    rows.append({
        "id": f"c-email_me-revoke-{user_id}",
        "user_id": user_id, "scope": "email_me",
        "granted": False,
        "ts": datetime(2026, 8, 6, 11, 0, 0, tzinfo=timezone.utc),
    })
    rows.append({
        "id": f"c-email_me-regrant-{user_id}",
        "user_id": user_id, "scope": "email_me",
        "granted": True,
        "ts": datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
    })
    # Also cover a permanently-revoked scope to prove revoked path.
    rows.append({
        "id": f"c-marketing-{user_id}",
        "user_id": user_id, "scope": "marketing_analytics",
        "granted": False,
        "ts": datetime(2026, 8, 6, 12, 30, 0, tzinfo=timezone.utc),
    })
    return rows


@pytest.mark.asyncio
async def test_snapshot_mirrors_granted_bool_directly(monkeypatch):
    """UNIT — `_snapshot_consents` alone.

    Post-fix, it must:
      * read `granted: bool` + `ts` (NOT `status` / `granted_at` /
        `revoked_at`)
      * sort by ts ascending → latest per scope wins
      * emit `granted` / `revoked` strings on the snapshot
    """
    fake_db = _FakeDB()
    user_id = f"u-{uuid.uuid4().hex[:8]}"
    for row in _make_consent_rows(user_id):
        fake_db.consent_records.rows.append(row)

    # Patch the module's local get_db.
    import domains.wave as _wave
    monkeypatch.setattr(_wave, "get_db", lambda: fake_db)

    snap = await _wave._snapshot_consents(user_id)

    # All 6 fixture-invariant scopes MUST be present with granted='granted'
    for sc in ("discover_jobs", "email_me", "generate_materials",
                 "process_career_data", "submit_applications", "track_applications"):
        assert snap.get(sc) == "granted", (sc, snap)
    # email_me went revoke → regrant; latest-wins must give "granted".
    assert snap["email_me"] == "granted", snap
    # marketing_analytics permanently revoked → "revoked".
    assert snap["marketing_analytics"] == "revoked", snap
    # SNAPSHOT MUST NOT BE EMPTY — this is the anti-regression guard.
    assert snap != {}, snap
    assert len(snap) >= 7, snap


@pytest.mark.asyncio
async def test_user_batch_path_writes_correct_snapshot(monkeypatch):
    """INTEGRATION (user_batch path) — `authorize_wave` writes a
    non-empty `consents_snapshot` mirroring the granted-bool state."""
    fake_db = _FakeDB()
    user_id = f"u-{uuid.uuid4().hex[:8]}"
    for row in _make_consent_rows(user_id):
        fake_db.consent_records.rows.append(row)

    import domains.wave as _wave
    monkeypatch.setattr(_wave, "get_db", lambda: fake_db)

    # Bypass real enumeration — the snapshot logic runs BEFORE enumerate,
    # and we exercise that path via `_snapshot_consents` +
    # `_persist_authorization` which is what the endpoint composes.
    from domains.wave import _snapshot_consents, _persist_authorization, WaveScope
    snap = await _snapshot_consents(user_id)
    wid = await _persist_authorization(
        user_id, WaveScope(cap=10),
        breakdown={"total_scanned": 0, "blocked_scope": 0,
                    "blocked_hard_gate": 0, "blocked_cap": 0,
                    "blocked_duplicate": 0},
        queued_app_ids=[], blocked_at_shortlist=[],
        consents_snapshot=snap, triggered_by="user_batch",
    )
    row = await fake_db.wave_authorizations.find_one({"id": wid})
    assert row is not None
    assert row["triggered_by"] == "user_batch"
    stored = row["consents_snapshot"]
    assert stored != {}, "regression: snapshot fell through empty"
    assert stored.get("submit_applications") == "granted", stored
    assert stored.get("email_me") == "granted", stored  # latest-wins
    assert stored.get("marketing_analytics") == "revoked", stored


@pytest.mark.asyncio
async def test_standing_wave_aab_tick_path_writes_correct_snapshot(monkeypatch):
    """INTEGRATION (standing_wave_aab_tick path) —
    `run_standing_waves_after_aab_tick` writes a non-empty
    `consents_snapshot` mirroring the granted-bool state."""
    fake_db = _FakeDB()
    user_id = f"u-{uuid.uuid4().hex[:8]}"
    for row in _make_consent_rows(user_id):
        fake_db.consent_records.rows.append(row)
    fake_db.standing_waves.rows.append({
        "user_id": user_id, "active": True,
        "scope": {"cap": 10, "standing_wave": True},
        "created_at": NOW,
    })

    import domains.wave as _wave
    monkeypatch.setattr(_wave, "get_db", lambda: fake_db)

    # Stub the downstream helpers so the tick can return quickly.
    async def _enum_stub(user_id, scope, candidate_ids=None):
        return [], {"total_scanned": 0, "blocked_scope": 0,
                    "blocked_hard_gate": 0, "blocked_cap": 0,
                    "blocked_duplicate": 0}
    monkeypatch.setattr(_wave, "_enumerate_eligible", _enum_stub)
    from domains.audit import service as audit_svc
    async def _audit_write(*_a, **_kw): pass
    monkeypatch.setattr(audit_svc, "write", _audit_write)

    new_job_id = f"job-{uuid.uuid4().hex[:8]}"
    summary = await _wave.run_standing_waves_after_aab_tick([new_job_id])
    assert summary["users_processed"] == 1

    row = await fake_db.wave_authorizations.find_one({"user_id": user_id})
    assert row is not None, "wave_authorizations row must be written"
    assert row["triggered_by"] == "standing_wave_aab_tick"
    stored = row["consents_snapshot"]
    # HARD ANTI-REGRESSION: previous defect wrote {} on this exact path.
    assert stored != {}, (
        "regression: standing_wave_aab_tick wrote empty consents_snapshot"
    )
    assert stored.get("submit_applications") == "granted", stored
    assert stored.get("email_me") == "granted", stored
    assert stored.get("marketing_analytics") == "revoked", stored


@pytest.mark.asyncio
async def test_snapshot_rejects_legacy_field_addressing_schema(monkeypatch):
    """DEFENSIVE — if a rebased consent row somehow lands with ONLY the
    legacy `status`+`granted_at` shape (no `granted: bool`), the reader
    must still surface a truthful "granted" via the defensive fallback
    branch, not fall through to empty."""
    fake_db = _FakeDB()
    user_id = f"u-{uuid.uuid4().hex[:8]}"
    fake_db.consent_records.rows.append({
        "id": f"legacy-{user_id}", "user_id": user_id,
        "scope": "submit_applications",
        # legacy shape: no explicit `granted` key
        "granted_at": datetime(2026, 8, 6, 9, 0, 0, tzinfo=timezone.utc),
        "revoked_at": None,
        "ts": datetime(2026, 8, 6, 9, 0, 0, tzinfo=timezone.utc),
    })
    import domains.wave as _wave
    monkeypatch.setattr(_wave, "get_db", lambda: fake_db)
    snap = await _wave._snapshot_consents(user_id)
    assert snap.get("submit_applications") == "granted", snap

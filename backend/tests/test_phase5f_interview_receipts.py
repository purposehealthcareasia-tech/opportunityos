"""Phase 5f · Interview outcome receipts tests."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException


class _Cursor:
    def __init__(self, docs): self._docs = list(docs)
    def sort(self, *_a, **_kw):
        # Sort by first key argument if it's `at`; default ascending unless -1
        return self
    def limit(self, *_a, **_kw): return self
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _AppsColl:
    def __init__(self, apps): self.apps = apps
    async def find_one(self, q, projection=None):
        for a in self.apps:
            if all(a.get(k) == v for k, v in q.items()):
                return a
        return None


class _OutcomesColl:
    def __init__(self): self.docs = []
    async def insert_one(self, d): self.docs.append(d)
    def find(self, q):
        rows = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False; break
                elif d.get(k) != v:
                    ok = False; break
            if ok:
                rows.append(d)
        rows.sort(key=lambda r: r.get("at") or "")
        c = _Cursor(rows)
        # Sort() ignored; docs pre-sorted ASC. limit() returns self,
        # so an explicit `.limit(1)` on descending will hit the LAST
        # doc via `async for` iteration below — but scheduled-list
        # helper in the service uses .sort("at", -1).limit(1) which
        # we approximate by reversing here when caller demands it.
        return c


class _RevCursor(_Cursor):
    def __init__(self, docs):
        super().__init__(sorted(docs, key=lambda r: r.get("at") or "", reverse=True))


class _OutcomesCollWithDesc(_OutcomesColl):
    """Wraps sort(-1).limit(1) semantics used in confirm_ghost."""
    def find(self, q):
        rows = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False; break
                elif d.get(k) != v:
                    ok = False; break
            if ok:
                rows.append(d)
        # A single-cursor object that supports both sort/limit + iteration.
        class _Both:
            def __init__(self, rows): self._rows = rows
            def sort(self, key, direction=1):
                self._rows.sort(key=lambda r: r.get(key) or "", reverse=(direction == -1))
                return self
            def limit(self, n):
                self._rows = self._rows[:n]
                return self
            def __aiter__(self):
                async def gen():
                    for r in self._rows:
                        yield r
                return gen()
        return _Both(rows)


class _DB:
    def __init__(self, apps, outcomes=None):
        self.applications = _AppsColl(apps)
        self.application_outcomes = _OutcomesCollWithDesc()
        if outcomes:
            for o in outcomes:
                self.application_outcomes.docs.append(o)


# ==================================================================
@pytest.mark.asyncio
async def test_record_event_persists_signed_row(monkeypatch):
    from domains.interview_receipts import service as ir
    from domains.interview_receipts.service import RecordEventRequest
    db = _DB(apps=[{"id": "app-0001", "user_id": "u1"}])
    monkeypatch.setattr(ir, "get_db", lambda: db)
    out = await ir.record_event(
        RecordEventRequest(application_id="app-0001",
                           event="interview_scheduled", notes="Zoom 3pm"),
        user={"id": "u1"},
    )
    assert out["recorded"] is True
    assert out["event"] == "interview_scheduled"
    assert len(out["signature"]) == 64  # HMAC-SHA256 hex
    assert out["verify_endpoint"].endswith("/exports/ghosting-evidence/verify")
    # Row persisted with signature
    assert len(db.application_outcomes.docs) == 1
    r = db.application_outcomes.docs[0]
    assert r["signature"] == out["signature"]
    assert r["notes"] == "Zoom 3pm"


@pytest.mark.asyncio
async def test_record_event_rejects_non_owner(monkeypatch):
    from domains.interview_receipts import service as ir
    from domains.interview_receipts.service import RecordEventRequest
    db = _DB(apps=[{"id": "app-0001", "user_id": "OTHER"}])
    monkeypatch.setattr(ir, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await ir.record_event(
            RecordEventRequest(application_id="app-0001",
                               event="interview_scheduled"),
            user={"id": "attacker"},
        )
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_list_events_derived_ghost_signal_after_threshold(monkeypatch):
    from domains.interview_receipts import service as ir
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    db = _DB(
        apps=[{"id": "app-0001", "user_id": "u1"}],
        outcomes=[
            {"id": "o1", "user_id": "u1", "application_id": "app-0001",
             "event": "interview_scheduled", "at": old, "signature": "abc"},
        ],
    )
    monkeypatch.setattr(ir, "get_db", lambda: db)
    out = await ir.list_events_for_application(
        application_id="app-0001", user={"id": "u1"},
    )
    assert out["count"] == 1
    assert out["derived_ghosting_signal"] is not None
    assert out["derived_ghosting_signal"]["would_be_ghosted"] is True
    assert out["derived_ghosting_signal"]["days_since_scheduled"] >= 14
    # DERIVED signal must never auto-write a receipt — check that no
    # ghost row was appended.
    events = [o["event"] for o in db.application_outcomes.docs]
    assert "interview_ghosted" not in events


@pytest.mark.asyncio
async def test_list_events_no_ghost_signal_when_within_threshold(monkeypatch):
    from domains.interview_receipts import service as ir
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    db = _DB(
        apps=[{"id": "app-0001", "user_id": "u1"}],
        outcomes=[
            {"id": "o1", "user_id": "u1", "application_id": "app-0001",
             "event": "interview_scheduled", "at": recent, "signature": "abc"},
        ],
    )
    monkeypatch.setattr(ir, "get_db", lambda: db)
    out = await ir.list_events_for_application(
        application_id="app-0001", user={"id": "u1"},
    )
    assert out["derived_ghosting_signal"] is None


@pytest.mark.asyncio
async def test_confirm_ghost_requires_prior_scheduled(monkeypatch):
    from domains.interview_receipts import service as ir
    from domains.interview_receipts.service import GhostConfirmRequest
    db = _DB(apps=[{"id": "app-0001", "user_id": "u1"}], outcomes=[])
    monkeypatch.setattr(ir, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await ir.confirm_ghost(
            GhostConfirmRequest(application_id="app-0001"),
            user={"id": "u1"},
        )
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "no_interview_scheduled"


@pytest.mark.asyncio
async def test_confirm_ghost_409_when_not_past_threshold(monkeypatch):
    from domains.interview_receipts import service as ir
    from domains.interview_receipts.service import GhostConfirmRequest
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db = _DB(
        apps=[{"id": "app-0001", "user_id": "u1"}],
        outcomes=[{"id": "o1", "user_id": "u1", "application_id": "app-0001",
                    "event": "interview_scheduled", "at": recent}],
    )
    monkeypatch.setattr(ir, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await ir.confirm_ghost(
            GhostConfirmRequest(application_id="app-0001"),
            user={"id": "u1"},
        )
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "not_yet_past_threshold"


@pytest.mark.asyncio
async def test_confirm_ghost_mints_signed_receipt(monkeypatch):
    from domains.interview_receipts import service as ir
    from domains.interview_receipts.service import GhostConfirmRequest
    old = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
    db = _DB(
        apps=[{"id": "app-0001", "user_id": "u1"}],
        outcomes=[{"id": "o1", "user_id": "u1", "application_id": "app-0001",
                    "event": "interview_scheduled", "at": old}],
    )
    monkeypatch.setattr(ir, "get_db", lambda: db)
    out = await ir.confirm_ghost(
        GhostConfirmRequest(application_id="app-0001"),
        user={"id": "u1"},
    )
    assert out["recorded"] is True
    assert len(out["signature"]) == 64
    events = [o["event"] for o in db.application_outcomes.docs]
    assert "interview_ghosted" in events
    ghost = next(o for o in db.application_outcomes.docs if o["event"] == "interview_ghosted")
    assert ghost["signature"] == out["signature"]
    assert "User-confirmed" in ghost["notes"]


@pytest.mark.asyncio
async def test_signature_verifies_via_existing_exports_verify(monkeypatch):
    """Cross-domain lock: a receipt minted by 5f MUST verify through
    the same verify endpoint Phase 4 exposed (single signing key,
    single canonical serializer, single verify path)."""
    from domains.interview_receipts import service as ir
    from domains.interview_receipts.service import RecordEventRequest
    from domains.exports.ghosting import ghosting_verify, VerifyRequest
    db = _DB(apps=[{"id": "app-0001", "user_id": "u1"}])
    monkeypatch.setattr(ir, "get_db", lambda: db)
    rec = await ir.record_event(
        RecordEventRequest(application_id="app-0001",
                           event="interview_completed"),
        user={"id": "u1"},
    )
    row = db.application_outcomes.docs[0]
    sign_body = {k: v for k, v in row.items() if k not in ("id", "signature", "signature_note")}
    verify = await ghosting_verify(VerifyRequest(manifest=sign_body, signature=rec["signature"]))
    assert verify["valid"] is True
    # Tampered payload flips it
    bad = dict(sign_body); bad["event"] = "interview_ghosted"
    verify_bad = await ghosting_verify(VerifyRequest(manifest=bad, signature=rec["signature"]))
    assert verify_bad["valid"] is False

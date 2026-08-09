"""Phase 5b · Material A/B — regression tests. Same fake-DB pattern."""
from __future__ import annotations

import pytest
from fastapi import HTTPException


class _Cursor:
    def __init__(self, docs): self._docs = list(docs)
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _AssignColl:
    def __init__(self, docs=None): self.docs = list(docs or [])
    async def find_one(self, q):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return d
        return None
    def find(self, q):
        rows = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False; break
                else:
                    if d.get(k) != v:
                        ok = False; break
            if ok:
                rows.append(d)
        return _Cursor(rows)
    async def insert_one(self, d): self.docs.append(d)
    async def update_one(self, q, upd):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                if "$set" in upd:
                    d.update(upd["$set"])
                return
        return None


class _AppsColl:
    def __init__(self, apps): self.apps = apps
    async def find_one(self, q):
        for a in self.apps:
            if all(a.get(k) == v for k, v in q.items()):
                return a
        return None


class _OutcomesColl:
    def __init__(self, outcomes): self.outcomes = outcomes
    def find(self, q):
        app_ids = q.get("application_id", {}).get("$in", [])
        events = q.get("event", {}).get("$in", [])
        rows = [
            o for o in self.outcomes
            if o["application_id"] in app_ids and o["event"] in events
        ]
        return _Cursor(rows)


class _DB:
    def __init__(self, assign=None, apps=None, outcomes=None):
        self.material_ab_assignments = _AssignColl(assign)
        self.applications = _AppsColl(apps or [])
        self.application_outcomes = _OutcomesColl(outcomes or [])


# ==================================================================
@pytest.mark.asyncio
async def test_attach_variant_creates_new_row(monkeypatch):
    from domains.materials_ab import service as m
    from domains.materials_ab.service import AttachRequest
    db = _DB(assign=[], apps=[{"id": "app-0001", "user_id": "u1"}])
    monkeypatch.setattr(m, "get_db", lambda: db)
    out = await m.attach_variant(
        AttachRequest(application_id="app-0001", generation_id="gen-0001",
                      variant_label="A", spectrum_key="senior-swe"),
        user={"id": "u1"},
    )
    assert out["attached"] is True and out["updated"] is False
    assert out["variant_label"] == "A"
    assert len(db.material_ab_assignments.docs) == 1
    assert db.material_ab_assignments.docs[0]["spectrum_key"] == "senior-swe"


@pytest.mark.asyncio
async def test_attach_variant_reject_non_owner(monkeypatch):
    from domains.materials_ab import service as m
    from domains.materials_ab.service import AttachRequest
    db = _DB(apps=[{"id": "app-0001", "user_id": "OTHER"}])
    monkeypatch.setattr(m, "get_db", lambda: db)
    with pytest.raises(HTTPException) as ei:
        await m.attach_variant(
            AttachRequest(application_id="app-0001", generation_id="gen-0001",
                          variant_label="A"),
            user={"id": "attacker"},
        )
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_attach_variant_re_attach_updates_label_and_preserves_id(monkeypatch):
    from domains.materials_ab import service as m
    from domains.materials_ab.service import AttachRequest
    db = _DB(
        assign=[{"id": "row-0001", "user_id": "u1", "application_id": "app-0001",
                 "generation_id": "gen-0001", "variant_label": "A"}],
        apps=[{"id": "app-0001", "user_id": "u1"}],
    )
    monkeypatch.setattr(m, "get_db", lambda: db)
    out = await m.attach_variant(
        AttachRequest(application_id="app-0001", generation_id="gen-0001",
                      variant_label="B"),
        user={"id": "u1"},
    )
    assert out["id"] == "row-0001" and out["updated"] is True
    assert db.material_ab_assignments.docs[0]["variant_label"] == "B"


@pytest.mark.asyncio
async def test_report_no_assignments_empty_and_small_n_true(monkeypatch):
    from domains.materials_ab import service as m
    db = _DB()
    monkeypatch.setattr(m, "get_db", lambda: db)
    out = await m.report(user={"id": "u1"})
    assert out["total_assignments"] == 0
    assert out["small_n"] is True
    assert out["variants"]["A"] == {"n": 0, "responded": 0, "response_rate": 0.0,
                                     "median_days_to_response": None}
    assert "nothing to describe" in out["cohort_notice"].lower()


@pytest.mark.asyncio
async def test_report_small_n_labels_correctly_and_no_significance_claim(monkeypatch):
    from domains.materials_ab import service as m
    # 3 apps under A (2 responded), 2 apps under B (1 responded)
    db = _DB(
        assign=[
            {"id": f"r{i}", "user_id": "u1", "application_id": f"a{i}",
             "generation_id": "g", "variant_label": "A" if i < 3 else "B",
             "spectrum_key": ""}
            for i in range(5)
        ],
        outcomes=[
            {"application_id": "a0", "event": "response_received", "lag_days": 2},
            {"application_id": "a1", "event": "interview_scheduled", "lag_days": 5},
            {"application_id": "a3", "event": "response_received", "lag_days": 3},
            # a2, a4 are ghosts.
        ],
    )
    monkeypatch.setattr(m, "get_db", lambda: db)
    out = await m.report(user={"id": "u1"})
    assert out["total_assignments"] == 5
    assert out["small_n"] is True
    assert out["variants"]["A"]["n"] == 3
    assert out["variants"]["A"]["responded"] == 2
    assert out["variants"]["A"]["response_rate"] == 0.6667
    assert out["variants"]["B"]["n"] == 2
    assert out["variants"]["B"]["responded"] == 1
    assert out["variants"]["B"]["response_rate"] == 0.5
    assert out["variants"]["A"]["median_days_to_response"] in (3.5, 3.500)
    # Cohort notice must NOT positively claim significance / a winner.
    for banned in ("is significant", "statistically significant beats",
                    "significant winner", "p-value", "winner is", "beats variant"):
        assert banned.lower() not in out["cohort_notice"].lower(), banned


@pytest.mark.asyncio
async def test_report_large_n_still_no_significance_claim_in_notice(monkeypatch):
    from domains.materials_ab import service as m
    # 30 apps under A, 30 apps under B
    assigns = []
    outcomes = []
    for i in range(60):
        v = "A" if i < 30 else "B"
        assigns.append({"id": f"r{i}", "user_id": "u1", "application_id": f"a{i}",
                        "generation_id": "g", "variant_label": v, "spectrum_key": ""})
        # 60% of A respond, 40% of B respond.
        if v == "A" and i < 18:
            outcomes.append({"application_id": f"a{i}", "event": "response_received", "lag_days": 4})
        if v == "B" and i < 30 + 12:
            outcomes.append({"application_id": f"a{i}", "event": "response_received", "lag_days": 6})
    db = _DB(assign=assigns, outcomes=outcomes)
    monkeypatch.setattr(m, "get_db", lambda: db)
    out = await m.report(user={"id": "u1"})
    assert out["small_n"] is False
    assert out["variants"]["A"]["n"] == 30 and out["variants"]["A"]["responded"] == 18
    assert out["variants"]["B"]["n"] == 30 and out["variants"]["B"]["responded"] == 12
    # Still descriptive-only — same anti-claim rails as small-n case.
    for banned in ("is significant", "statistically significant beats",
                    "significant winner", "p-value", "winner is", "beats variant"):
        assert banned.lower() not in out["cohort_notice"].lower(), banned

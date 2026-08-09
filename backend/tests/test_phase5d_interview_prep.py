"""Phase 5d · Interview Prep — regression tests (LLM mocked via monkeypatch)."""
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


class _Claims:
    def __init__(self, docs): self.docs = docs
    def find(self, *_a, **_kw): return _Cursor(self.docs)


class _Gen:
    def __init__(self): self.docs = []
    async def insert_one(self, d): self.docs.append(d)


class _DB:
    def __init__(self, claims):
        self.claims = _Claims(claims)
        self.interview_prep_generations = _Gen()


# ==================================================================
def test_tokens_of_extracts_alphanum():
    from domains.interview_prep.service import _tokens_of
    assert "python" in _tokens_of("Python 3.11 backend")
    assert "2018" in _tokens_of(2018)
    assert _tokens_of(None) == set()


def test_build_claim_block_filters_approved_only():
    from domains.interview_prep.service import _build_claim_block
    claims = [
        {"kind": "education", "state": "approved",
         "data": {"school": "State U", "degree": "BSc", "field": "CS", "graduation_year": 2018}},
        {"kind": "education", "state": "pending",
         "data": {"school": "Never Approved"}},
        {"kind": "employment", "state": "approved",
         "data": {"title": "Eng", "company": "Acme"}},
    ]
    block, tokens = _build_claim_block(claims, "education")
    assert len(block) == 1
    assert block[0]["school"] == "State U"
    assert "state" in tokens and "2018" in tokens
    # employment claim not included when category=education
    assert not any(b.get("title") for b in block)


def test_validation_firewall_drops_ungrounded_answers():
    from domains.interview_prep.service import _validation_firewall
    claim_tokens = {"python", "acme", "state", "2018"}
    qas = [
        {"question": "Q1", "sample_answer": "I worked at Acme on backend systems."},
        {"question": "Q2", "sample_answer": "I love Ruby on Rails and skateboarding."},
        {"question": "Q3", "sample_answer": "Yes I my we and the."},  # only generic
    ]
    kept, dropped = _validation_firewall(qas, claim_tokens)
    assert len(kept) == 1
    assert kept[0]["question"] == "Q1"
    assert "Q2" in dropped and "Q3" in dropped


# ==================================================================
@pytest.mark.asyncio
async def test_generate_prep_empty_state_when_no_approved_claims_in_category(monkeypatch):
    from domains.interview_prep import service as ip
    from domains.interview_prep.service import PrepRequest
    db = _DB(claims=[
        # user has other-category claims but none approved for `education`
        {"kind": "employment", "state": "approved", "data": {"title": "Eng"}},
    ])
    monkeypatch.setattr(ip, "get_db", lambda: db)
    out = await ip.generate_prep(
        PrepRequest(category="education", question_count=3),
        user={"id": "u1"},
    )
    assert out["empty_state"] is True
    assert out["practice_questions"] == []
    assert out["reason"] == "no_approved_claims_in_category"
    # No LLM call happened → no generation row written
    assert len(db.interview_prep_generations.docs) == 0


@pytest.mark.asyncio
async def test_generate_prep_happy_path_firewall_kept(monkeypatch):
    from domains.interview_prep import service as ip
    from domains.interview_prep.service import PrepRequest
    db = _DB(claims=[
        {"id": "c1", "kind": "employment", "state": "approved",
         "data": {"title": "Software Engineer", "company": "Acme",
                  "start_year": 2019, "end_year": 2023}},
    ])
    monkeypatch.setattr(ip, "get_db", lambda: db)

    # LLM mock returns a grounded answer (uses "Acme" from claim) and an
    # ungrounded answer (Ruby/skateboarding — must be dropped).
    fake_raw = (
        '```json\n{"practice_questions": ['
        '{"question":"Tell me about your work at Acme?", '
        '"sample_answer":"At Acme I built backend software.", "grounded_in":["c1"]},'
        '{"question":"Hobbies?", '
        '"sample_answer":"I enjoy Ruby and skateboarding.", "grounded_in":[]}'
        '], "prep_summary":"Practice grounded in your Acme claim."}\n```'
    )
    async def fake_llm(*_a, **_kw):
        return "gpt-4o", fake_raw, 100, 50
    monkeypatch.setattr(ip, "_generate_via_llm", fake_llm)

    out = await ip.generate_prep(
        PrepRequest(category="employment", question_count=2),
        user={"id": "u1"},
    )
    assert out["empty_state"] is False
    assert len(out["practice_questions"]) == 1
    assert out["practice_questions"][0]["question"].startswith("Tell me about")
    assert out["firewall"]["kept"] == 1
    assert out["firewall"]["dropped"] == 1
    assert "Hobbies?" in out["firewall"]["dropped_preview"]
    assert "practice" in out["labeled_as"].lower()
    # Generation row logged
    assert len(db.interview_prep_generations.docs) == 1
    row = db.interview_prep_generations.docs[0]
    assert row["kept_count"] == 1 and row["dropped_by_firewall_count"] == 1


@pytest.mark.asyncio
async def test_generate_prep_never_invents_when_llm_returns_all_ungrounded(monkeypatch):
    from domains.interview_prep import service as ip
    from domains.interview_prep.service import PrepRequest
    db = _DB(claims=[
        {"id": "c1", "kind": "skill", "state": "approved",
         "data": {"name": "kubernetes", "level": "advanced"}},
    ])
    monkeypatch.setattr(ip, "get_db", lambda: db)
    fake_raw = (
        '{"practice_questions": ['
        '{"question":"Hobbies?", "sample_answer":"I like painting."},'
        '{"question":"Weather?", "sample_answer":"It rains often."}'
        '], "prep_summary":"Off-topic prep"}'
    )
    async def fake_llm(*_a, **_kw): return "gpt-4o", fake_raw, 10, 5
    monkeypatch.setattr(ip, "_generate_via_llm", fake_llm)
    out = await ip.generate_prep(
        PrepRequest(category="skill", question_count=2),
        user={"id": "u2"},
    )
    # Firewall dropped everything → kept list empty, but empty_state stays
    # False because we DID have approved claims (the LLM just failed to
    # ground). This is the honest failure mode.
    assert out["practice_questions"] == []
    assert out["firewall"]["kept"] == 0 and out["firewall"]["dropped"] == 2
    assert out["empty_state"] is False


@pytest.mark.asyncio
async def test_generate_prep_502_on_llm_json_parse_failure(monkeypatch):
    from domains.interview_prep import service as ip
    from domains.interview_prep.service import PrepRequest
    db = _DB(claims=[
        {"id": "c1", "kind": "project", "state": "approved",
         "data": {"name": "Fynd", "description": "job search"}},
    ])
    monkeypatch.setattr(ip, "get_db", lambda: db)
    async def fake_llm(*_a, **_kw): return "gpt-4o", "this is not json", 10, 5
    monkeypatch.setattr(ip, "_generate_via_llm", fake_llm)
    with pytest.raises(HTTPException) as ei:
        await ip.generate_prep(
            PrepRequest(category="project", question_count=2),
            user={"id": "u1"},
        )
    assert ei.value.status_code == 502
    assert ei.value.detail["error"] == "llm_returned_unparseable_json"

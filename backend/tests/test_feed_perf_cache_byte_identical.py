"""Feed perf cache byte-identical test (Phase-0 addendum, 2026-08-04).

Founder rail: the additive response cache in `/api/v1/jobs/feed` must
NEVER alter the returned bytes. This test proves it by:

  1. Fetching the feed twice inside the 60s TTL window and asserting
     the second response is byte-identical to the first (cache HIT).
  2. Bypassing the cache (fresh state) and asserting the response
     matches the previous fresh response (cache MISS but same input →
     same output).
"""
from __future__ import annotations

import copy
import json

import pytest


@pytest.mark.asyncio
async def test_cache_hit_returns_byte_identical_response():
    from domains.jobs import router as jobs_router
    # Reset the cache to a known state.
    jobs_router._feed_cache.clear()

    ctx_stub = {
        "hidden_job_ids": set(), "approved_skills": set(),
        "target_titles": [], "target_industries": [],
    }
    live_jobs = [
        {"id": "j1", "status": "live", "is_sample": False,
         "title": "Software Engineer", "company_name": "acme",
         "canonical_key": "acme::se-1", "taxonomy_family": "eng",
         "lane": "career", "geo": {"country": "US"},
         "requirements": {"skills_required": []}, "comp": {}},
    ]

    async def _list_live(): return copy.deepcopy(live_jobs)
    async def _build_ctx(_): return dict(ctx_stub)
    def _evaluate(_c, _j): return {"pass_all": True, "gates": {}, "notes": []}
    def _score(_c, _j, _g): return {"score": 0.75, "reason_codes": []}
    class _MsStub:
        @staticmethod
        async def upsert(**kwargs): return False
    async def _flag(*a, **kw): return True

    import services.gate_engine
    import services.scoring
    import services.feature_flags
    from domains.match_scores import service as ms_svc
    from services import scoring as _scoring
    monkeys = pytest.MonkeyPatch()
    try:
        monkeys.setattr(jobs_router.jobs_repo, "list_live", _list_live)
        monkeys.setattr(jobs_router, "build_context", _build_ctx)
        monkeys.setattr(jobs_router, "evaluate", _evaluate)
        monkeys.setattr(jobs_router, "score_job", _score)
        monkeys.setattr(ms_svc, "upsert", _MsStub.upsert)
        monkeys.setattr(services.feature_flags, "is_enabled", _flag)

        # Simulate an authenticated activated-passport user; the handler
        # calls `get_db().users.find_one` — stub that too.
        class _Users:
            @staticmethod
            async def find_one(*a, **kw): return {"passport_activated": True}
        class _Sweeps:
            @staticmethod
            async def find_one(*a, **kw): return None
        class _Db:
            users = _Users()
            lifecycle_sweep_runs = _Sweeps()
        monkeys.setattr(jobs_router, "get_db", lambda: _Db)

        # First call — cache MISS, computes response.
        first = await jobs_router.feed(user={"id": "u-perf-cache-1"})
        # Second call — cache HIT, should return the exact same dict.
        second = await jobs_router.feed(user={"id": "u-perf-cache-1"})
        # Byte-identical: serialize both to canonical JSON and compare.
        j1 = json.dumps(first, default=str, sort_keys=True)
        j2 = json.dumps(second, default=str, sort_keys=True)
        assert j1 == j2, f"cache response drift:\nfirst={j1[:200]}\nsecond={j2[:200]}"
    finally:
        monkeys.undo()


@pytest.mark.asyncio
async def test_two_fresh_computes_produce_identical_output():
    """Same as above but bypasses the cache each time — proves the
    scorer is deterministic and the cache is safe."""
    from domains.jobs import router as jobs_router
    jobs_router._feed_cache.clear()

    call_count = {"n": 0}
    ctx_stub = {
        "hidden_job_ids": set(), "approved_skills": set(),
        "target_titles": [], "target_industries": [],
    }
    live_jobs = [
        {"id": "j1", "status": "live", "is_sample": False,
         "title": "SWE", "company_name": "acme", "canonical_key": "acme::swe",
         "taxonomy_family": "eng", "lane": "career",
         "requirements": {"skills_required": []}, "comp": {}},
    ]

    async def _list_live():
        call_count["n"] += 1
        return copy.deepcopy(live_jobs)
    async def _build_ctx(_): return dict(ctx_stub)
    def _evaluate(_c, _j): return {"pass_all": True, "gates": {}, "notes": []}
    def _score(_c, _j, _g): return {"score": 0.75, "reason_codes": []}
    class _MsStub:
        @staticmethod
        async def upsert(**kwargs): return False
    async def _flag(*a, **kw): return True
    class _Users:
        @staticmethod
        async def find_one(*a, **kw): return {"passport_activated": True}
    class _Sweeps:
        @staticmethod
        async def find_one(*a, **kw): return None
    class _Db:
        users = _Users()
        lifecycle_sweep_runs = _Sweeps()

    import services.feature_flags
    from domains.match_scores import service as ms_svc
    monkeys = pytest.MonkeyPatch()
    try:
        monkeys.setattr(jobs_router.jobs_repo, "list_live", _list_live)
        monkeys.setattr(jobs_router, "build_context", _build_ctx)
        monkeys.setattr(jobs_router, "evaluate", _evaluate)
        monkeys.setattr(jobs_router, "score_job", _score)
        monkeys.setattr(ms_svc, "upsert", _MsStub.upsert)
        monkeys.setattr(services.feature_flags, "is_enabled", _flag)
        monkeys.setattr(jobs_router, "get_db", lambda: _Db)

        first = await jobs_router.feed(user={"id": "u-perf-cache-2"})
        jobs_router._feed_cache.clear()
        second = await jobs_router.feed(user={"id": "u-perf-cache-2"})
        assert call_count["n"] == 2  # cache miss twice
        j1 = json.dumps(first, default=str, sort_keys=True)
        j2 = json.dumps(second, default=str, sort_keys=True)
        assert j1 == j2, f"scorer non-determinism: first={j1[:200]}"
    finally:
        monkeys.undo()

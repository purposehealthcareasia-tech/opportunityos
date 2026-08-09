"""Phase 5e · Responds-fast badge tests."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_responds_fast_map_omits_no_data_employers(monkeypatch):
    from domains.badges import service as b
    async def fake_stats(*_a, **_kw):
        return {
            "acme": {"median_days_to_response": 2.0, "submitted": 10,
                     "response": 5, "interview": 2, "rejection": 1},
            "slowcorp": {"median_days_to_response": 21.0, "submitted": 4,
                         "response": 2, "interview": 0, "rejection": 0},
            "nostats": {"submitted": 0},  # no median → omit
        }
    from services import outcome_autopilot
    monkeypatch.setattr(outcome_autopilot, "compute_group_stats", fake_stats)
    out = await b.responds_fast_map(user={"id": "u1"})
    # acme qualifies (median=2 ≤3 and 8 responded ≥3); slowcorp too slow;
    # nostats has no median → omitted.
    assert "acme" in out["responds_fast"]
    assert "slowcorp" not in out["responds_fast"]
    assert "nostats" not in out["responds_fast"]
    assert out["responds_fast"]["acme"]["fast"] is True
    assert out["responds_fast"]["acme"]["median_days_to_response"] == 2.0
    assert out["count"] == 1
    # Rails: threshold block advertised
    assert out["thresholds"]["median_days_max"] == 3
    assert out["thresholds"]["min_responses"] == 3


@pytest.mark.asyncio
async def test_responds_fast_map_never_marks_slow(monkeypatch):
    from domains.badges import service as b
    async def fake_stats(*_a, **_kw):
        return {
            "slowcorp": {"median_days_to_response": 45.0, "submitted": 100,
                         "response": 20, "interview": 0, "rejection": 30},
        }
    from services import outcome_autopilot
    monkeypatch.setattr(outcome_autopilot, "compute_group_stats", fake_stats)
    out = await b.responds_fast_map(user={"id": "u1"})
    # Never a "slow" badge — omission only.
    assert out["responds_fast"] == {}
    # No `fast: false` / `slow: true` in any employer row (the map is
    # a per-employer positive-only signal; slow employers are OMITTED).
    for row in out["responds_fast"].values():
        assert row.get("fast") is not False
    # Notice explicitly advertises the "no negative badge" rail.
    assert "never shows a 'slow' badge" in out["notice"].lower()


@pytest.mark.asyncio
async def test_responds_fast_map_min_sample_size_gate(monkeypatch):
    from domains.badges import service as b
    async def fake_stats(*_a, **_kw):
        return {
            # Fast median but only 2 responses → below _FAST_MIN_RESPONSES.
            "fastbutthin": {"median_days_to_response": 1.0, "submitted": 5,
                            "response": 2, "interview": 0, "rejection": 0},
            # Fast + enough responses → qualifies.
            "fastok":      {"median_days_to_response": 3.0, "submitted": 8,
                            "response": 2, "interview": 1, "rejection": 1},
        }
    from services import outcome_autopilot
    monkeypatch.setattr(outcome_autopilot, "compute_group_stats", fake_stats)
    out = await b.responds_fast_map(user={"id": "u1"})
    assert "fastbutthin" not in out["responds_fast"]
    assert "fastok" in out["responds_fast"]


@pytest.mark.asyncio
async def test_responds_fast_map_soft_fails_when_service_raises(monkeypatch):
    from domains.badges import service as b
    async def fake_stats(*_a, **_kw): raise RuntimeError("boom")
    from services import outcome_autopilot
    monkeypatch.setattr(outcome_autopilot, "compute_group_stats", fake_stats)
    out = await b.responds_fast_map(user={"id": "u1"})
    # Never propagates an error — returns an empty map, honest state.
    assert out["responds_fast"] == {}
    assert out["count"] == 0

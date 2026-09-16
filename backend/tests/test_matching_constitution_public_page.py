"""Tests for the auto-generated /standards/matching-constitution page.

Batch 5 constraint: the page must be AUTO-GENERATED from the live
gate + ranking registries so it cannot drift from the code. These
tests exercise the handler at the module level (no HTTP layer needed)
so the assertion is on the actual JSON payload the endpoint would
return.
"""
from __future__ import annotations

import pytest

from domains.matching import GATE_REGISTRY, RANKING_REGISTRY
from domains.standards.service import matching_constitution


@pytest.mark.asyncio
async def test_endpoint_lists_every_registered_gate():
    payload = await matching_constitution()
    gate_ids_in_payload = {g["id"] for g in payload["stage_1_gates"]}
    gate_ids_in_registry = {g.id for g in GATE_REGISTRY}
    assert gate_ids_in_payload == gate_ids_in_registry


@pytest.mark.asyncio
async def test_endpoint_lists_every_registered_signal():
    payload = await matching_constitution()
    sig_ids_in_payload = {s["id"] for s in payload["stage_2_ranking_signals"]}
    sig_ids_in_registry = {s.id for s in RANKING_REGISTRY}
    assert sig_ids_in_payload == sig_ids_in_registry


@pytest.mark.asyncio
async def test_gate_entries_carry_outcomes_and_evidence():
    payload = await matching_constitution()
    for g in payload["stage_1_gates"]:
        assert set(g.keys()) >= {
            "id", "family", "description", "is_hard_exclusion",
            "possible_outcomes", "required_evidence",
            "what_would_change_it",
        }
        # Outcomes are strings from the allowed set.
        allowed = set(payload["gate_outcome_types"])
        assert set(g["possible_outcomes"]).issubset(allowed)


@pytest.mark.asyncio
async def test_signal_entries_carry_direction_and_evidence():
    payload = await matching_constitution()
    for s in payload["stage_2_ranking_signals"]:
        assert set(s.keys()) >= {
            "id", "description", "direction", "evidence",
            "what_would_change_it",
        }
        assert s["direction"] in payload["ranking_directions"]


@pytest.mark.asyncio
async def test_constitution_version_fingerprint_is_stable_per_registry():
    """The version fingerprint depends only on the current registry
    contents — calling twice in a row yields the same value."""
    p1 = await matching_constitution()
    p2 = await matching_constitution()
    assert p1["constitution_version"] == p2["constitution_version"]
    assert p1["constitution_version"].startswith("c-")


@pytest.mark.asyncio
async def test_gate_outcome_types_matches_enum():
    payload = await matching_constitution()
    assert set(payload["gate_outcome_types"]) == {
        "pass", "fail", "unknown", "candidate_confirmation_required",
    }


@pytest.mark.asyncio
async def test_ranking_directions_matches_enum():
    payload = await matching_constitution()
    assert set(payload["ranking_directions"]) == {
        "positive", "negative", "neutral",
    }


@pytest.mark.asyncio
async def test_no_hand_written_prose_leaks_into_gate_fields():
    """Rail: every human-visible field on a gate MUST be sourced
    from the registry — no hard-coded strings in the handler that
    the registry does not also carry. We check by asserting the
    handler's per-gate description exactly equals the registry
    entry's description (byte-for-byte)."""
    payload = await matching_constitution()
    by_id = {g.id: g for g in GATE_REGISTRY}
    for g in payload["stage_1_gates"]:
        spec = by_id[g["id"]]
        assert g["description"] == spec.description
        assert g["family"] == spec.family
        assert g["is_hard_exclusion"] is spec.is_hard_exclusion


@pytest.mark.asyncio
async def test_rails_and_note_are_present():
    """The page carries the fixed rails/note block that explains what
    the reader is looking at."""
    payload = await matching_constitution()
    assert isinstance(payload["rails"], list) and payload["rails"]
    assert "auto_generated" in {r["rail"] for r in payload["rails"]}
    assert "stage_separation" in {r["rail"] for r in payload["rails"]}
    assert payload["note"]

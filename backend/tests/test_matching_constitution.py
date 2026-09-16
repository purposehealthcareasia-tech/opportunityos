"""Matching Constitution tests — stage-separation invariant + behavior.

Covers Batch 5 Constitution requirements:

  * Architectural: `matching.ranking` may NOT import `matching.gates`
    at the AST level. This is the STRUCTURAL invariant that a Stage 2
    signal cannot even read a Stage 1 outcome.

  * Architectural (symmetric): `matching.gates` may NOT import
    `matching.ranking`. The stages are true islands.

  * Behavioral: `evaluator.evaluate()` short-circuits Stage 2 the
    moment ANY Stage 1 gate returns `fail`, even if the caller passed
    non-empty signal contributions.

  * Registry integrity: gate IDs and signal IDs are disjoint, every
    gate declares its permitted outcome set, note-only gates cannot
    emit `fail`.

  * Result envelope: `positive`, `negative`, `unknown`,
    `what_would_change_it` are all present on the returned dict; no
    protected attribute names appear in any registry.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from domains.matching import (
    ConstitutionResult,
    GATE_REGISTRY,
    GateOutcome,
    RANKING_REGISTRY,
    SignalDirection,
    evaluate,
)
from domains.matching.gates.outcomes import GateOutcome as _GateOutcome
from domains.matching.gates.registry import HARD_EXCLUSION_FAMILIES


BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
MATCHING_ROOT = BACKEND_ROOT / "domains" / "matching"


# =====================================================================
# 1. Architectural invariants — import-graph enforcement
# =====================================================================
def _files_importing(target_pkg: str, under: pathlib.Path) -> list[str]:
    """Return relative paths of *.py files under `under` whose AST
    contains any import that references `target_pkg`. Both
    `import X` and `from X import Y` count."""
    offenders: list[str] = []
    for path in under.rglob("*.py"):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == target_pkg or alias.name.startswith(target_pkg + "."):
                        offenders.append(rel)
                        break
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == target_pkg or mod.startswith(target_pkg + "."):
                    offenders.append(rel)
                    break
    return offenders


def test_ranking_module_does_not_import_gates():
    """STRUCTURAL: a ranking signal cannot even see a gate outcome.

    Enforced via AST scan of every file under
    `domains/matching/ranking/`. If any file imports
    `domains.matching.gates` (directly or via a submodule) the test
    fails. This is the primary artifact of the founder's Batch 5
    correction: 'assert at the import/module level (ranking module
    cannot import or mutate gate outcomes) in addition to the
    behavioral check.'
    """
    offenders = _files_importing(
        target_pkg="domains.matching.gates",
        under=MATCHING_ROOT / "ranking",
    )
    assert not offenders, (
        "Stage 2 must not import Stage 1. The ranking module cannot "
        "mutate or even read gate outcomes; that composition is the "
        "evaluator's sole responsibility. Offenders: "
        f"{offenders}"
    )


def test_gates_module_does_not_import_ranking():
    """SYMMETRIC island invariant — gates must not know about ranking
    signals either. This keeps both stages independently reasonable-
    about."""
    offenders = _files_importing(
        target_pkg="domains.matching.ranking",
        under=MATCHING_ROOT / "gates",
    )
    assert not offenders, (
        f"Stage 1 must not import Stage 2. Offenders: {offenders}"
    )


def test_evaluator_is_the_only_bridge():
    """The evaluator is the ONLY file under `domains/matching/` that
    imports BOTH stages. Anything else that touches both stages must
    be added deliberately (this test forces the review moment)."""
    both_importers: list[str] = []
    for path in MATCHING_ROOT.rglob("*.py"):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        src = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue
        imports_gates = imports_ranking = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("domains.matching.gates"):
                    imports_gates = True
                if mod.startswith("domains.matching.ranking"):
                    imports_ranking = True
        if imports_gates and imports_ranking:
            both_importers.append(rel)
    # `__init__.py` and `evaluator.py` are the two intentional
    # bridges. Anything else is a regression.
    permitted = {
        "domains/matching/__init__.py",
        "domains/matching/evaluator.py",
    }
    extras = [f for f in both_importers if f not in permitted]
    assert not extras, (
        "Only the evaluator (and the package __init__ re-exports) may "
        "bridge Stage 1 and Stage 2. New bridge files must be added "
        f"to the permitted set with review. Extras: {extras}"
    )


# =====================================================================
# 2. Registry integrity
# =====================================================================
def test_gate_ids_are_unique_and_kebab_case():
    ids = [g.id for g in GATE_REGISTRY]
    assert len(ids) == len(set(ids)), f"duplicate gate ids: {ids}"
    for gid in ids:
        assert gid.replace("_", "").isalnum() and gid.islower(), (
            f"gate id must be snake_case-lower-alnum, got {gid!r}"
        )


def test_signal_ids_are_unique_and_kebab_case():
    ids = [s.id for s in RANKING_REGISTRY]
    assert len(ids) == len(set(ids)), f"duplicate signal ids: {ids}"
    for sid in ids:
        assert sid.replace("_", "").isalnum() and sid.islower(), (
            f"signal id must be snake_case-lower-alnum, got {sid!r}"
        )


def test_gate_and_signal_ids_are_disjoint():
    gate_ids = {g.id for g in GATE_REGISTRY}
    signal_ids = {s.id for s in RANKING_REGISTRY}
    overlap = gate_ids & signal_ids
    assert not overlap, (
        "gate ids and signal ids must not overlap; the two stages must "
        f"be namewise disjoint. Overlap: {overlap}"
    )


def test_note_only_gates_declare_only_pass():
    """A note-only gate is DECLARED with `possible_outcomes = (PASS,)`.
    Enforcing this at registration time makes it impossible for a
    future contributor to add a `FAIL` outcome to a note-only gate
    without also lying in the declaration — which the constitution
    page would then render as a lie."""
    for g in GATE_REGISTRY:
        if not g.is_hard_exclusion:
            assert g.possible_outcomes == (GateOutcome.PASS,), (
                f"note-only gate {g.id!r} may only declare PASS as a "
                f"possible outcome; declared: {g.possible_outcomes}"
            )


def test_hard_exclusion_gates_belong_to_permitted_families():
    for g in GATE_REGISTRY:
        if g.is_hard_exclusion:
            assert g.family in HARD_EXCLUSION_FAMILIES, (
                f"gate {g.id!r} is is_hard_exclusion=True but belongs "
                f"to family {g.family!r}, which is not in "
                f"HARD_EXCLUSION_FAMILIES={HARD_EXCLUSION_FAMILIES}"
            )


def test_no_protected_attribute_references_in_registries():
    """ATLAS: no protected attribute, no inference of one."""
    banned_substrings = {
        "race", "ethnicity", "gender", "sex", "age_", "birthdate",
        "national_origin", "religion", "marital", "parental",
        "disability", "sexual_orientation", "veteran",
    }
    def _scan(items, kind):
        for item in items:
            parts: list[str] = [item.id, item.description or ""]
            parts.extend(getattr(item, "required_evidence", ()) or ())
            parts.extend(getattr(item, "evidence", ()) or ())
            parts.extend(item.what_would_change_it or ())
            haystack = " ".join(parts).lower()
            hits = [b for b in banned_substrings if b in haystack]
            assert not hits, (
                f"{kind} {item.id!r} references protected attribute "
                f"substring(s) {hits}; ATLAS forbids protected "
                "attributes in any registry."
            )
    _scan(GATE_REGISTRY, "gate")
    _scan(RANKING_REGISTRY, "signal")


# =====================================================================
# 3. Behavioral — evaluator short-circuits & envelope
# =====================================================================
def _all_gate_pass_records() -> list[dict]:
    """Fixture: every gate emits PASS with empty evidence."""
    return [{"id": g.id, "outcome": GateOutcome.PASS, "evidence": {}}
            for g in GATE_REGISTRY]


def test_stage2_short_circuits_on_stage1_fail():
    """BEHAVIORAL invariant matching the architectural test. When
    even one Stage 1 gate is `fail`, `ranking_factors` MUST be empty
    regardless of what the caller passed in."""
    gates = _all_gate_pass_records()
    # Flip work_auth to FAIL.
    for g in gates:
        if g["id"] == "work_auth":
            g["outcome"] = GateOutcome.FAIL
            g["reason"] = "test_forced_fail"
    # Provide non-empty signal contributions — evaluator MUST drop them.
    signals = [
        {"id": "skill_overlap_approved", "value": 7, "evidence": {"count": 7}},
        {"id": "urgency_expiring_soon",  "value": 1, "evidence": {"days_to_close": 3}},
    ]
    result = evaluate(gate_outcomes=gates, signal_contributions=signals)
    assert isinstance(result, ConstitutionResult)
    assert result.stage1_short_circuited is True
    assert result.terminal_fail_gate_id == "work_auth"
    assert result.ranking_factors == (), (
        "Stage 2 signals must not be evaluated when a Stage 1 gate "
        "failed. Actual: "
        f"{[r.to_dict() for r in result.ranking_factors]}"
    )
    # And the failure must appear in `negative`.
    assert "gate:work_auth" in result.negative


def test_stage2_runs_when_stage1_all_pass():
    gates = _all_gate_pass_records()
    signals = [
        {"id": "skill_overlap_approved", "value": 4, "evidence": {"count": 4}},
    ]
    result = evaluate(gate_outcomes=gates, signal_contributions=signals)
    assert result.stage1_short_circuited is False
    assert result.terminal_fail_gate_id is None
    # Every declared signal produces an entry (silent ones as
    # value=None, present ones with the passed value).
    assert len(result.ranking_factors) == len(RANKING_REGISTRY)
    by_id = {r.spec.id: r for r in result.ranking_factors}
    assert by_id["skill_overlap_approved"].value == 4
    # Any signal not in the input is silent (value=None).
    silent = [r for r in result.ranking_factors if r.value is None]
    assert len(silent) == len(RANKING_REGISTRY) - 1


def test_missing_gate_defaults_to_unknown():
    """If the runtime omits a gate record, the evaluator must NOT
    fabricate a pass. It surfaces UNKNOWN with reason=
    gate_result_missing."""
    gates = _all_gate_pass_records()
    # Drop `licensure`.
    gates = [g for g in gates if g["id"] != "licensure"]
    result = evaluate(gate_outcomes=gates, signal_contributions=[])
    lic = next(g for g in result.gate_outcomes if g.spec.id == "licensure")
    assert lic.outcome is GateOutcome.UNKNOWN
    assert lic.reason == "gate_result_missing"
    assert "gate:licensure" in result.unknown


def test_note_only_gate_cannot_return_fail():
    """A misbehaving runtime that tries to fail a note-only gate must
    be rejected at evaluator time — the platform never silently
    accepts an over-filter."""
    gates = _all_gate_pass_records()
    for g in gates:
        if g["id"] == "salary_floor":
            g["outcome"] = GateOutcome.FAIL
    with pytest.raises(ValueError, match="note-only"):
        evaluate(gate_outcomes=gates, signal_contributions=[])


def test_candidate_confirmation_required_is_a_valid_outcome():
    """The FOURTH outcome must round-trip through the envelope."""
    gates = _all_gate_pass_records()
    for g in gates:
        if g["id"] == "work_auth":
            g["outcome"] = GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED
            g["reason"] = "candidate_status_missing"
    result = evaluate(gate_outcomes=gates, signal_contributions=[])
    assert result.stage1_short_circuited is False  # not a `fail`
    assert "gate:work_auth" in result.unknown


def test_result_envelope_shape():
    """The envelope shape matches ATLAS exactly."""
    result = evaluate(
        gate_outcomes=_all_gate_pass_records(),
        signal_contributions=[
            {"id": "liveness_confidence", "value": 0.9, "evidence": {"sources": 2}}
        ],
    )
    d = result.to_dict()
    assert set(d.keys()) == {
        "gate_outcomes", "ranking_factors",
        "positive", "negative", "unknown",
        "stage1_short_circuited", "terminal_fail_gate_id",
    }
    for g in d["gate_outcomes"]:
        assert set(g.keys()) >= {
            "id", "family", "is_hard_exclusion", "outcome",
            "evidence", "reason", "note", "what_would_change_it",
        }
    for r in d["ranking_factors"]:
        assert set(r.keys()) >= {
            "id", "direction", "value", "evidence",
            "what_would_change_it",
        }


def test_gate_outcome_enum_has_exactly_four_values():
    """The four-outcome contract is the ATLAS invariant. If someone
    adds a fifth, the constitution page + the runtime must be
    reviewed together, so trip the test."""
    assert set(_GateOutcome) == {
        _GateOutcome.PASS, _GateOutcome.FAIL,
        _GateOutcome.UNKNOWN,
        _GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED,
    }


def test_signal_direction_enum_shape():
    assert set(SignalDirection) == {
        SignalDirection.POSITIVE, SignalDirection.NEGATIVE,
        SignalDirection.NEUTRAL,
    }

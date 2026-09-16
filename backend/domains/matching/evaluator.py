"""Matching Constitution evaluator.

The evaluator is the ONLY module allowed to import from BOTH
`matching.gates` AND `matching.ranking`. It composes a Stage 1 pass
(gates) with a Stage 2 pass (ranking signals) into a single
`ConstitutionResult`.

Invariants enforced STRUCTURALLY in this module (not just tested):

  1. If ANY gate in Stage 1 returns `fail`, Stage 2 is not entered
     and no ranking signal is invoked. The `ranking_factors` field of
     the result is the empty tuple. This is enforced by the control-
     flow of `evaluate()`, and it is validated behaviorally by the
     test `test_stage2_short_circuits_on_stage1_fail`.

  2. A ranking signal has no read-access to gate outcomes. This is
     enforced STRUCTURALLY by the import-graph invariant: no file
     under `domains/matching/ranking/` may import `matching.gates`.
     Validated architecturally by
     `test_ranking_module_does_not_import_gates`.

  3. Every result carries an evidence payload. If evidence is
     missing for a gate or a signal, the field is `None` — never a
     fabricated placeholder value, never zero-standing-for-missing.

Note: the evaluator does NOT re-implement the runtime gate logic.
`services/gate_engine.py` remains the runtime. This module accepts
pre-computed gate outcomes + pre-computed signal contributions
produced against the runtime, then assembles the Constitution's
result envelope from them. That separation keeps the Constitution a
pure spec-and-assembly layer and keeps the runtime free to evolve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domains.matching.gates.outcomes import GateOutcome
from domains.matching.gates.registry import GATE_REGISTRY, GateSpec
from domains.matching.ranking.registry import (
    RANKING_REGISTRY,
    RankingSignalSpec,
)


# --------------------------------------------------------------------
# Input shapes — kept as plain dicts / tuples so callers can build
# them from any runtime (services/gate_engine.py today; possibly a
# rewritten runtime later) without importing model classes.
# --------------------------------------------------------------------
GateOutcomeRecord = dict[str, Any]
"""Shape: {'id': str, 'outcome': GateOutcome | str, 'evidence': dict,
'reason': str | None, 'note': str | None}."""

SignalContribution = dict[str, Any]
"""Shape: {'id': str, 'value': Any | None, 'evidence': dict | None}.
`value` MAY be None to indicate 'silent — insufficient evidence'."""


@dataclass(frozen=True)
class GateOutcomeEntry:
    """Normalized gate outcome, backed by a registry spec."""
    spec: GateSpec
    outcome: GateOutcome
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.spec.id,
            "family": self.spec.family,
            "is_hard_exclusion": self.spec.is_hard_exclusion,
            "outcome": self.outcome.value,
            "evidence": self.evidence,
            "reason": self.reason,
            "note": self.note,
            "what_would_change_it": list(self.spec.what_would_change_it),
        }


@dataclass(frozen=True)
class RankingFactorEntry:
    """Normalized ranking factor, backed by a registry spec.

    `value=None` means the signal was silent because evidence was
    missing. Silence is FIRST-CLASS — never coerced into a zero or a
    negative contribution.
    """
    spec: RankingSignalSpec
    value: Any | None
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.spec.id,
            "direction": self.spec.direction.value,
            "value": self.value,
            "evidence": self.evidence,
            "what_would_change_it": list(self.spec.what_would_change_it),
        }


@dataclass(frozen=True)
class ConstitutionResult:
    """The single, complete result envelope produced for one
    (candidate, opportunity) pair.

    Fields mirror the ATLAS `every result carries: why passed, why
    ranked, positive/negative/unknown factors, evidence, and what-
    would-change-it` contract exactly.
    """
    gate_outcomes: tuple[GateOutcomeEntry, ...]
    ranking_factors: tuple[RankingFactorEntry, ...]
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    unknown: tuple[str, ...]
    stage1_short_circuited: bool
    terminal_fail_gate_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_outcomes":            [g.to_dict() for g in self.gate_outcomes],
            "ranking_factors":          [r.to_dict() for r in self.ranking_factors],
            "positive":                 list(self.positive),
            "negative":                 list(self.negative),
            "unknown":                  list(self.unknown),
            "stage1_short_circuited":   self.stage1_short_circuited,
            "terminal_fail_gate_id":    self.terminal_fail_gate_id,
        }


def _coerce_outcome(raw: Any) -> GateOutcome:
    """Accept either a `GateOutcome` or its string value. Strict —
    anything else raises `ValueError`."""
    if isinstance(raw, GateOutcome):
        return raw
    if isinstance(raw, str):
        return GateOutcome(raw)  # raises ValueError on unknown values
    raise ValueError(f"unrecognized gate outcome: {raw!r}")


def _index_gate_records(records: list[GateOutcomeRecord]) -> dict[str, GateOutcomeRecord]:
    idx: dict[str, GateOutcomeRecord] = {}
    for r in records:
        gid = r.get("id")
        if not gid:
            raise ValueError("gate outcome record missing 'id'")
        idx[gid] = r
    return idx


def _index_signal_records(records: list[SignalContribution]) -> dict[str, SignalContribution]:
    idx: dict[str, SignalContribution] = {}
    for r in records:
        sid = r.get("id")
        if not sid:
            raise ValueError("signal contribution record missing 'id'")
        idx[sid] = r
    return idx


def evaluate(
    *,
    gate_outcomes: list[GateOutcomeRecord],
    signal_contributions: list[SignalContribution] | None = None,
) -> ConstitutionResult:
    """Assemble the ATLAS result envelope for a (candidate, opportunity)
    pair from pre-computed inputs.

    Contract:
      * `gate_outcomes` MUST include one record per gate declared in
        `GATE_REGISTRY`. Missing entries default to `unknown` with
        empty evidence so the platform never silently drops a gate.
      * `signal_contributions` is optional. If any Stage 1 gate is
        `fail`, Stage 2 is NEVER entered — even if the caller passed
        signal contributions, they are discarded and the result's
        `ranking_factors` is empty. This is the STRUCTURAL invariant
        that a Stage 2 signal cannot override a Stage 1 fail.
      * Result also carries the ordered `positive/negative/unknown`
        summaries so the UI can render "why" bullets without
        reprocessing the payload.
    """
    gate_idx = _index_gate_records(gate_outcomes)

    normalized_gates: list[GateOutcomeEntry] = []
    terminal_fail: str | None = None
    for spec in GATE_REGISTRY:
        rec = gate_idx.get(spec.id)
        if rec is None:
            # Missing gate → surface UNKNOWN, don't fabricate a pass.
            entry = GateOutcomeEntry(
                spec=spec,
                outcome=GateOutcome.UNKNOWN,
                evidence={},
                reason="gate_result_missing",
            )
        else:
            outcome = _coerce_outcome(rec.get("outcome"))
            # Structural guard: a note-only gate MUST NOT emit fail.
            if not spec.is_hard_exclusion and outcome is GateOutcome.FAIL:
                raise ValueError(
                    f"gate '{spec.id}' is note-only (family="
                    f"{spec.family}); it may never emit 'fail'. Fix "
                    "the runtime that produced this record."
                )
            entry = GateOutcomeEntry(
                spec=spec,
                outcome=outcome,
                evidence=rec.get("evidence") or {},
                reason=rec.get("reason"),
                note=rec.get("note"),
            )
        normalized_gates.append(entry)
        if entry.outcome is GateOutcome.FAIL and terminal_fail is None:
            terminal_fail = spec.id

    # STRUCTURAL INVARIANT: Stage 2 is skipped iff any gate failed.
    stage1_short_circuited = terminal_fail is not None

    ranking_entries: list[RankingFactorEntry] = []
    if not stage1_short_circuited and signal_contributions:
        sig_idx = _index_signal_records(signal_contributions)
        for spec in RANKING_REGISTRY:
            rec = sig_idx.get(spec.id)
            if rec is None:
                # Silence is first-class — no fabricated value.
                ranking_entries.append(RankingFactorEntry(
                    spec=spec, value=None, evidence=None,
                ))
                continue
            ranking_entries.append(RankingFactorEntry(
                spec=spec,
                value=rec.get("value"),
                evidence=rec.get("evidence"),
            ))

    positive: list[str] = []
    negative: list[str] = []
    unknown: list[str] = []
    for g in normalized_gates:
        if g.outcome is GateOutcome.PASS:
            if g.note:
                # NOTE-on-pass surfaces as a positive-visible bullet.
                positive.append(f"gate:{g.spec.id}")
        elif g.outcome is GateOutcome.FAIL:
            negative.append(f"gate:{g.spec.id}")
        elif g.outcome is GateOutcome.UNKNOWN:
            unknown.append(f"gate:{g.spec.id}")
        elif g.outcome is GateOutcome.CANDIDATE_CONFIRMATION_REQUIRED:
            unknown.append(f"gate:{g.spec.id}")
    for r in ranking_entries:
        if r.value is None:
            unknown.append(f"signal:{r.spec.id}")
        else:
            positive.append(f"signal:{r.spec.id}")

    return ConstitutionResult(
        gate_outcomes=tuple(normalized_gates),
        ranking_factors=tuple(ranking_entries),
        positive=tuple(positive),
        negative=tuple(negative),
        unknown=tuple(unknown),
        stage1_short_circuited=stage1_short_circuited,
        terminal_fail_gate_id=terminal_fail,
    )

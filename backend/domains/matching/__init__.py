"""FYND ATLAS Matching Constitution.

Public entry-point for the Matching Constitution. The Constitution is
the declarative, introspectable spec of:

  * Stage 1 — deterministic qualification GATES (pass | fail | unknown
    | candidate_confirmation_required).
  * Stage 2 — explainable ranking SIGNALS.

The two are hard-separated at the import level: `matching.ranking` may
NOT import from `matching.gates`, and `matching.gates` may NOT import
from `matching.ranking`. The `evaluator` composes both.

FYND ATLAS invariants encoded here:

  * A Stage 2 signal cannot override a Stage 1 fail. Enforced
    STRUCTURALLY by the evaluator's control flow AND by an
    architectural test at the import graph level.
  * No protected attributes, no inference of protected attributes, no
    auto-penalty for gaps, no false precision.
  * Every result carries: `gate_outcomes`, `ranking_factors`,
    `evidence`, `what_would_change_it`, `positive`, `negative`,
    `unknown`.

The Constitution is READ by (never written by) the auto-generated
`/standards/matching-constitution` public page. The page renders the
live registries so it cannot drift.
"""
from domains.matching.evaluator import (  # noqa: F401
    ConstitutionResult,
    evaluate,
)
from domains.matching.gates.outcomes import GateOutcome  # noqa: F401
from domains.matching.gates.registry import (  # noqa: F401
    GATE_REGISTRY,
    GateSpec,
)
from domains.matching.ranking.registry import (  # noqa: F401
    RANKING_REGISTRY,
    RankingSignalSpec,
    SignalDirection,
)

__all__ = [
    "ConstitutionResult",
    "evaluate",
    "GateOutcome",
    "GATE_REGISTRY",
    "GateSpec",
    "RANKING_REGISTRY",
    "RankingSignalSpec",
    "SignalDirection",
]

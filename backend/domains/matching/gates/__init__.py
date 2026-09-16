"""Stage 1 gates package.

`gates/` is an ISLAND — it must not import from `matching.ranking`.
The stage-separation architectural test asserts this.
"""
from domains.matching.gates.outcomes import GateOutcome  # noqa: F401
from domains.matching.gates.registry import (  # noqa: F401
    GATE_REGISTRY,
    GateSpec,
    HARD_EXCLUSION_FAMILIES,
    by_id,
)

__all__ = ["GateOutcome", "GATE_REGISTRY", "GateSpec",
           "HARD_EXCLUSION_FAMILIES", "by_id"]

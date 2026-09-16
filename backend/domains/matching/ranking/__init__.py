"""Stage 2 ranking package.

`ranking/` is an ISLAND — it MUST NOT import from `matching.gates`.
The stage-separation architectural test asserts this at the import
graph level (AST scan of every file under `matching/ranking/`).

Consequence: a ranking signal cannot even SEE a gate outcome. The
`matching.evaluator` is the only module that speaks to both sides.
"""
from domains.matching.ranking.registry import (  # noqa: F401
    RANKING_REGISTRY,
    RankingSignalSpec,
    SignalDirection,
    by_id,
)

__all__ = ["RANKING_REGISTRY", "RankingSignalSpec",
           "SignalDirection", "by_id"]

"""Lanes render orchestrator.

Wraps every registered lane's selector into a uniform envelope so the
UI has ONE shape to render:

    LaneRenderResult:
      lane_id, title, description, matches[], count,
      empty_state, empty_reason, requires_confidence_display

Empty-state honesty rules (ATLAS):
  * If `lawful_source_available=False` → empty, `empty_reason=
    "no_lawful_source_yet"`. Applies to future lanes like Income Now.
  * If `count < min_n_for_public_render` → empty,
    `empty_reason="insufficient_n"`. The lane's rows are STILL
    computed (so admin/telemetry can see them) but not rendered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domains.lanes.registry import (
    LANE_REGISTRY,
    LaneContext,
    LaneMatch,
    LaneSpec,
)


@dataclass(frozen=True)
class LaneRenderResult:
    lane_id: str
    title: str
    description: str
    matches: tuple[LaneMatch, ...]
    count: int
    empty_state: bool
    empty_reason: str | None
    requires_confidence_display: bool
    reason_schema: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane_id":                     self.lane_id,
            "title":                       self.title,
            "description":                 self.description,
            "matches": [
                {"job_id": m.job_id, "reason": m.reason}
                for m in self.matches
            ],
            "count":                       self.count,
            "empty_state":                 self.empty_state,
            "empty_reason":                self.empty_reason,
            "requires_confidence_display": self.requires_confidence_display,
            "reason_schema":               list(self.reason_schema),
        }


def render_lane(spec: LaneSpec,
                 ctx: LaneContext,
                 opportunities: list[dict]) -> LaneRenderResult:
    """Run one lane's selector and wrap in the empty-state envelope."""
    if not spec.lawful_source_available:
        return LaneRenderResult(
            lane_id=spec.id,
            title=spec.title,
            description=spec.description,
            matches=(),
            count=0,
            empty_state=True,
            empty_reason="no_lawful_source_yet",
            requires_confidence_display=spec.requires_confidence_display,
            reason_schema=spec.reason_schema,
        )
    matches = tuple(spec.selector(ctx, opportunities))
    count = len(matches)
    if count < spec.min_n_for_public_render:
        return LaneRenderResult(
            lane_id=spec.id,
            title=spec.title,
            description=spec.description,
            matches=(),   # do NOT surface partial rows; honest empty
            count=count,  # count preserved for telemetry
            empty_state=True,
            empty_reason="insufficient_n",
            requires_confidence_display=spec.requires_confidence_display,
            reason_schema=spec.reason_schema,
        )
    return LaneRenderResult(
        lane_id=spec.id,
        title=spec.title,
        description=spec.description,
        matches=matches,
        count=count,
        empty_state=False,
        empty_reason=None,
        requires_confidence_display=spec.requires_confidence_display,
        reason_schema=spec.reason_schema,
    )


def render_all(ctx: LaneContext,
                opportunities: list[dict]) -> list[LaneRenderResult]:
    """Render every registered lane in declaration order."""
    return [render_lane(spec, ctx, opportunities) for spec in LANE_REGISTRY]

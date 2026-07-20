"""Plan config — Phase 5 enforcement is limited to the DAILY SUBMIT CAP only.

Full billing (Stripe subscriptions, plan upgrades/downgrades, prepared/processed
caps) lands in Phase 6. Here we ship the enum + the per-plan cap and the plumbing
so submit-time refusal is truthful and consistent with the founder brief.

Caps come from the founder brief:
  free 3/day, plus 15/day, pro 25/day, max 40/day
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanConfig:
    slug: str
    label: str
    daily_submit_cap: int


PLANS: dict[str, PlanConfig] = {
    "free": PlanConfig(slug="free", label="Free",  daily_submit_cap=3),
    "plus": PlanConfig(slug="plus", label="Plus",  daily_submit_cap=15),
    "pro":  PlanConfig(slug="pro",  label="Pro",   daily_submit_cap=25),
    "max":  PlanConfig(slug="max",  label="Max",   daily_submit_cap=40),
}

DEFAULT_PLAN = "free"


def resolve(plan_slug: str | None) -> PlanConfig:
    return PLANS.get(plan_slug or DEFAULT_PLAN, PLANS[DEFAULT_PLAN])

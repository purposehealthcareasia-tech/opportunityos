"""Application route engine — Batch 5 public entry-point.

Every opportunity resolves to exactly one of the seven ATLAS route
types. See `engine.py` for the resolver + specs.
"""
from domains.applications.routes.engine import (  # noqa: F401
    AutomationLevel,
    ROUTE_REGISTRY,
    RouteSpec,
    RouteType,
    get_spec,
    resolve_route,
)

__all__ = [
    "AutomationLevel",
    "ROUTE_REGISTRY",
    "RouteSpec",
    "RouteType",
    "get_spec",
    "resolve_route",
]

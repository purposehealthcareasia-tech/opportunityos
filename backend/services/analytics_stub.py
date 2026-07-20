"""INTERNAL STUB — product analytics.

Interface preserved for later swap. In Phase 1 this only logs.
"""
import logging

log = logging.getLogger("oppos.analytics_stub")


async def track(user_id: str | None, event: str, props: dict | None = None) -> None:
    log.info("STUB analytics.track user=%s event=%s props=%s", user_id, event, props or {})

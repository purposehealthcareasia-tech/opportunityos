"""INTERNAL STUB — error tracking (Sentry etc.).

Interface preserved for later swap. In Phase 1 this only logs.
"""
import logging

log = logging.getLogger("oppos.error_tracking_stub")


def capture(exc: BaseException, context: dict | None = None) -> None:
    log.exception("STUB error_tracking.capture context=%s", context or {}, exc_info=exc)

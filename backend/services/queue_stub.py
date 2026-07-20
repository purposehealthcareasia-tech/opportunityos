"""INTERNAL STUB — background task queue.

Phase 2 implementation uses asyncio tasks bounded by a semaphore. The interface is intentionally
narrow so Phase 5+ can swap in a real queue (Celery / RQ / Dramatiq / SQS) without touching callers.
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger("oppos.queue_stub")

_semaphore = asyncio.Semaphore(4)
_registered: set[asyncio.Task] = set()


def enqueue(coro_factory: Callable[[], Awaitable[Any]], *, name: str | None = None) -> asyncio.Task:
    """Fire-and-forget a coroutine.

    Accepts a callable (thunk) that returns a coroutine, not a coroutine directly, so callers can
    postpone async construction until inside the task.
    """
    async def _runner() -> None:
        async with _semaphore:
            try:
                await coro_factory()
            except Exception:
                log.exception("queue_stub task %r failed", name)

    task = asyncio.create_task(_runner(), name=name or "queue_stub")
    _registered.add(task)
    task.add_done_callback(_registered.discard)
    return task

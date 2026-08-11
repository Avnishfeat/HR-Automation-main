"""Own and drain interview tasks created by this API process.

This is intentionally process-local.  It makes graceful shutdown possible in
the single-worker deployment without pretending to provide durable jobs.
"""

import asyncio
import logging
from typing import Awaitable

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}


def create_interview_task(session_id: str, work: Awaitable[None]) -> asyncio.Task:
    if session_id in _tasks and not _tasks[session_id].done():
        raise RuntimeError(f"Interview task already exists for {session_id}")

    task = asyncio.create_task(work, name=f"Interview-{session_id[:8]}")
    _tasks[session_id] = task

    def _remove(completed: asyncio.Task) -> None:
        _tasks.pop(session_id, None)
        try:
            completed.result()
        except asyncio.CancelledError:
            logger.warning("Interview task cancelled during shutdown: %s", session_id)
        except Exception:
            logger.exception("Interview task failed unexpectedly: %s", session_id)

    task.add_done_callback(_remove)
    return task


def active_task_count() -> int:
    return sum(not task.done() for task in _tasks.values())


def is_task_active(session_id: str) -> bool:
    task = _tasks.get(session_id)
    return task is not None and not task.done()


async def drain_interview_tasks(timeout_seconds: float = 25.0) -> None:
    """Wait for normal cleanup, then cancel only tasks that did not drain."""
    tasks = [task for task in _tasks.values() if not task.done()]
    if not tasks:
        return

    _, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
    if pending:
        logger.warning("Cancelling %s interview task(s) after shutdown deadline", len(pending))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

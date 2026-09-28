"""Starting a claimed job off the request — the shape two admin routes share.

The colorway harvest and the full re-pricing sweep both answer 202 and keep
working after the response: claim a slot synchronously in the request, start
the work with `create_task`, hold a strong reference to the task, release the
slot however the work ends. Each route carried its own copy of those four
steps, and the copies are exactly where the permanent-lockout bugs they each
document came from — a claim whose release a code path skipped.

`create_task`, not `BackgroundTasks`: Starlette runs background tasks only
after the response has been sent, so a response that fails to send — a phone
dropping the LAN just after the 202 — never runs the task, and nothing then
releases the claim. `create_task` schedules immediately.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


def launch(
    work: Coroutine[Any, Any, None],
    *,
    release: Callable[[], None],
    running: set[asyncio.Task],
) -> asyncio.Task:
    """Run `work` in the background, releasing its claim when it ends.

    `running` holds the strong reference. asyncio keeps only a weak one to a
    running task, so without it the collector can take the job mid-flight —
    and a job that vanishes never reaches the `finally` that releases the
    claim. Per-route sets, so a test can await exactly its own route's work.

    `finally`, not `except Exception`: `CancelledError` is a `BaseException`,
    and a job canceled at shutdown that kept its slot would refuse every press
    after the next start.
    """

    async def _run() -> None:
        try:
            await work
        finally:
            release()

    task = asyncio.create_task(_run())
    running.add(task)
    task.add_done_callback(running.discard)
    return task

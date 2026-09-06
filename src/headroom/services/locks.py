"""In-process locks for the read-then-write sequences a single process runs.

The app is single-process by design (CLAUDE.md: the rate limiter, the
passkey challenge store, both queues and the token caches all live in
memory), so an `asyncio.Lock` IS the right serialization for a sequence that
reads committed state, decides, writes and commits — placing a hat, numbering
a case, importing an order file. Two such sequences interleaving at an
`await` both see the same empty slot; measured on a file-backed database, ten
concurrent assigns into a 3-hat case landed five hats at position 1, and two
concurrent imports of one order file wrote every row twice.

One lock per (name, event loop) rather than a module-level `asyncio.Lock`:
a lock binds itself to the loop that first makes it wait, and the test suite
runs every test on a fresh loop, so a module-level lock contended in one
test raises "bound to a different event loop" in the next. Production has
exactly one loop and therefore exactly one lock per name.
"""

from __future__ import annotations

import asyncio
import weakref

_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def loop_lock(name: str) -> asyncio.Lock:
    """The lock called `name` for the running event loop, created on first use."""
    loop = asyncio.get_running_loop()
    locks = _by_loop.get(loop)
    if locks is None:
        locks = _by_loop[loop] = {}
    lock = locks.get(name)
    if lock is None:
        lock = locks[name] = asyncio.Lock()
    return lock

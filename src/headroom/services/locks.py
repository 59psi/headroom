"""In-process locks for the read-then-write sequences a single process runs.

The app is single-process by design (the rate limiter, the passkey
challenge store, both queues and the token caches all live in memory — see
`app._warn_if_multiprocess`), so an `asyncio.Lock` IS the right serialization for a sequence that
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

Semaphores have the same binding, so they come from here too
(`loop_semaphore`): a bound on concurrent work — argon2 hashing, rembg
inference — is a lock that admits `n` holders, and a lazily created
module-level one still binds to whichever loop first contends it. Lazy
creation only moves the moment of binding; it does not remove it.
"""

from __future__ import annotations

import asyncio
import weakref

_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)

#: Separate from `_by_loop` so a lock and a semaphore that happen to share a
#: name are still two primitives, not one answering to both helpers.
_semaphores_by_loop: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, tuple[int, asyncio.Semaphore]]
] = weakref.WeakKeyDictionary()


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


def loop_semaphore(name: str, value: int) -> asyncio.Semaphore:
    """The semaphore called `name` for the running event loop, admitting `value`.

    Created on first use per loop. Every caller of one name must agree on
    `value`: two call sites asking for the same bound with different sizes is
    two ideas of the limit, and silently honoring whichever ran first would
    make the bound depend on call order — so a disagreement raises instead.
    """
    loop = asyncio.get_running_loop()
    semaphores = _semaphores_by_loop.get(loop)
    if semaphores is None:
        semaphores = _semaphores_by_loop[loop] = {}
    entry = semaphores.get(name)
    if entry is None:
        entry = semaphores[name] = (value, asyncio.Semaphore(value))
    elif entry[0] != value:
        raise ValueError(
            f"semaphore {name!r} already exists with value {entry[0]}, not {value}"
        )
    return entry[1]

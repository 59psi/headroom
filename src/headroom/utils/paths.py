"""Confining a user-supplied path to a directory.

There are three places that serve a file chosen by something the client
controls — the SPA fallback, the share-link photo streamer, and anything that
follows them — and each one had its own copy of the containment check. Two
correct copies of a security check is not twice as safe: it is two places that
must both be updated when the check is wrong, and one of them will be missed.

One definition, one test.
"""

from __future__ import annotations

from pathlib import Path


def safe_join(root: Path, *parts: str) -> Path | None:
    """Resolve `parts` under `root`, or None if the result escapes it.

    `None` rather than an exception because every caller's response to "that
    isn't in there" is the same 404, and a traversal attempt should be
    indistinguishable from a genuine miss — telling an attacker which of the
    two happened is free information.

    Both sides are resolved before comparison: `root` may itself be a symlink
    (a `/data` bind mount typically is), and comparing a resolved candidate
    against an unresolved root rejects every legitimate path underneath it.
    """
    try:
        base = root.resolve(strict=False)
        candidate = base.joinpath(*parts).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        # RuntimeError: symlink loop. ValueError: embedded NUL byte, which
        # reaches here from a query string rather than from a real filename.
        return None
    if candidate != base and not candidate.is_relative_to(base):
        return None
    return candidate


def safe_file(root: Path, *parts: str) -> Path | None:
    """`safe_join`, but also require the result to be an existing regular file.

    A directory that resolves inside `root` is still not something to hand to
    `FileResponse`, and neither is a dangling symlink.
    """
    candidate = safe_join(root, *parts)
    if candidate is None or not candidate.is_file():
        return None
    return candidate

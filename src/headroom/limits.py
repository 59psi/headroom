"""A ceiling on how much body an ordinary request may send.

Every upload route in this app is careful: photos are spooled to disk in
capped chunks, bulk import bounds both per-file and per-batch bytes, and peak
memory on any upload path is one chunk or one file. None of that protected the
*other* routes. A JSON POST to `/api/auth/login` — which is open, because it
has to be — was read into memory in full and then parsed, and 20 MB of JSON
costs several times its own size once Python has objects for it. On a box with
a 1 GB limit, that is a denial of service anyone on the LAN can perform with
one curl command and no credentials.

Two properties worth stating:

**Multipart is exempt**, because those routes already stream to disk with
their own, much larger, deliberate caps. Applying a small JSON-shaped limit to
them would break bulk import; applying bulk import's 750 MB to JSON would
protect nothing.

**Bytes are counted, not trusted.** `Content-Length` is checked first because
rejecting before reading is strictly better, but a request may lie or omit it
entirely (chunked transfer), so the body is also counted as it streams and cut
off the moment it goes over.
"""

from __future__ import annotations

import logging

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from headroom.config import env_int

logger = logging.getLogger(__name__)

#: Generous for anything this app legitimately sends as JSON or a form — the
#: largest is a hat update with notes — and small enough that a flood of them
#: cannot exhaust a 1 GB container.
DEFAULT_MAX_BODY_BYTES = 2 * 1024 * 1024


def max_body_bytes() -> int:
    """Live-read so it stays monkeypatchable, like the other runtime knobs."""
    return env_int("HEADROOM_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)


class BodySizeLimitMiddleware:
    """Reject non-multipart request bodies over the cap with a 413.

    Pure ASGI rather than `BaseHTTPMiddleware`: the latter buffers the whole
    body to hand a `Request` object to the handler, which is precisely the
    cost this exists to avoid.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        content_type = headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            # Upload routes: capped per-file and per-batch as they stream to
            # disk. See `utils.upload` and `routes/import_jobs`.
            return await self.app(scope, receive, send)

        limit = max_body_bytes()

        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    return await _reject(scope, send, limit)
            except ValueError:
                pass  # unparseable; the streaming count below still applies

        # A chunked request declares no Content-Length, so the count below is
        # the only limit that applies to it — and it has to end the same way
        # the declared path does, with a 413.
        #
        # It used to return `{"type": "http.disconnect"}`, and the comment
        # claimed that let "the request fail as the malformed thing it is".
        # It does not: Starlette's `Request.stream()` turns a disconnect into
        # `ClientDisconnect`, which no handler catches, so it reached
        # `error_handler.log_unhandled` and produced a 500 AND a durable
        # `error.unhandled` activity row. On an open endpoint like
        # `/api/auth/login` that made an oversize chunked body an
        # unauthenticated way to write an audit row per request — the same
        # disk-filling shape as the rate-limit branch. Two halves of one
        # middleware, disagreeing about what "refused" means.
        over_limit = False
        received = 0

        async def counting_receive() -> Message:
            nonlocal received, over_limit
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    over_limit = True
                    logger.warning(
                        "Request body over the %d byte limit on %s %s — refused.",
                        limit, scope["method"], scope.get("path", ""),
                    )
                    # Stop the body cleanly. The route sees a complete (short)
                    # body rather than a disconnect, and `guarded_send` below
                    # replaces whatever it decides with the 413.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        # The route still runs — it has to, because the cap is only known once
        # the body has been read past it — but its response never reaches the
        # client. Swapping at the `http.response.start` boundary means nothing
        # partial has been written yet.
        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if over_limit:
                if not started:
                    started = True
                    await _reject(scope, send, limit)
                return  # drop the route's own body chunks
            await send(message)

        await self.app(scope, counting_receive, guarded_send)


async def _reject(scope: Scope, send: Send, limit: int) -> None:
    logger.warning(
        "Rejected oversize body on %s %s (limit %d bytes).",
        scope["method"], scope.get("path", ""), limit,
    )
    body = b'{"detail":"Request body too large"}'
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})

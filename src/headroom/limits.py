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

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Truncate rather than pass it on. Raising here would
                    # surface as a 500 from inside the route; ending the body
                    # early lets the request fail as the malformed thing it is.
                    logger.warning(
                        "Request body over the %d byte limit on %s %s — truncated.",
                        limit, scope["method"], scope.get("path", ""),
                    )
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, counting_receive, send)


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

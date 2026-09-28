"""A ceiling on how much body a request may send.

Every upload route in this app is careful: photos are spooled to disk in
capped chunks, bulk import bounds both per-file and per-batch bytes, and peak
memory on any upload path is one chunk or one file. None of that protected the
*other* routes. A JSON POST to `/api/auth/login` — which is open, because it
has to be — was read into memory in full and then parsed, and 20 MB of JSON
costs several times its own size once Python has objects for it. On a box with
a 1 GB limit, that is a denial of service anyone on the LAN can perform with
one curl command and no credentials.

Three properties worth stating:

**The cap is chosen by the ENDPOINT, never by the client's Content-Type.**
The first version exempted any request labeled `multipart/form-data`, on the
reasoning that upload routes carry their own caps. The label is the client's
to choose: a JSON route reads its body whole before the parse fails, so an
anonymous 900 MB POST to the login route with a multipart label was buffered
entire — the one-curl-command denial of service this module exists to
prevent, through the door it left open. Measured live: 50 MB JSON-typed was
cut at 786 KB; the same bytes multipart-typed were accepted in full. Which
endpoint is reading the body is known the moment it reads — the router has
put `endpoint` on the scope by then — so the cap is decided there:
`MULTIPART_MAX_BODY_BYTES` for an endpoint that takes an `UploadFile`, the
ordinary cap for everything else. `endpoint_streams_files` derives that from
the signature, because a roster of upload paths would rot the day a fifth
one landed.

**Even an upload route has a ceiling.** Starlette parses the whole multipart
stream before the handler runs, spooling each part to disk; the route's own
per-file and per-batch caps apply to what it reads back afterwards. Without a
wire ceiling a client could stream any number of bytes at the SD card the
spool lives on. The ceiling is the bulk-import batch cap plus framing — the
largest body any route here legitimately accepts.

**Bytes are counted, not trusted.** `Content-Length` is checked first because
rejecting before reading is strictly better, but a request may lie or omit it
entirely (chunked transfer), so the body is also counted as it streams and cut
off the moment it goes over — and "cut off" means the handler never runs on
what arrived before the cut. A 413 is a promise that nothing happened.
"""

from __future__ import annotations

import functools
import logging
import typing
from collections.abc import Callable

from fastapi import UploadFile
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from headroom.config import env_int
from headroom.services.import_service import MAX_TOTAL_UPLOAD_BYTES

logger = logging.getLogger(__name__)

#: Generous for anything this app legitimately sends as JSON or a form — the
#: largest is a hat update with notes — and small enough that a flood of them
#: cannot exhaust a 1 GB container.
DEFAULT_MAX_BODY_BYTES = 2 * 1024 * 1024

#: The largest body any endpoint here accepts: a full bulk-import batch, plus
#: room for multipart boundaries, part headers and filenames. Applied only to
#: endpoints that take an `UploadFile`; module-level so a test can lower it.
MULTIPART_MAX_BODY_BYTES = MAX_TOTAL_UPLOAD_BYTES + 4 * 1024 * 1024


#: Below this no request body of any kind can arrive — a login is ~60 bytes
#: of JSON. `HEADROOM_MAX_BODY_BYTES=0` (or `-1`) made every POST a 413,
#: including the one at `/api/auth/login`, which is a lock-out by typo.
MIN_MAX_BODY_BYTES = 1024


def max_body_bytes() -> int:
    """`HEADROOM_MAX_BODY_BYTES`: the cap for every endpoint that takes no file.

    Chosen by endpoint, not by the request's Content-Type — a multipart-labeled
    body sent to a JSON route gets this cap too. Endpoints that take an
    `UploadFile` get `MULTIPART_MAX_BODY_BYTES` instead, which this knob does
    not move. A value below `MIN_MAX_BODY_BYTES` (or one that does not parse)
    is ignored in favor of the default, for the lock-out reason given there.

    Live-read so it stays monkeypatchable, like the other runtime knobs.
    """
    value = env_int("HEADROOM_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)
    return value if value >= MIN_MAX_BODY_BYTES else DEFAULT_MAX_BODY_BYTES


def _mentions_upload_file(annotation: object) -> bool:
    if annotation is UploadFile:
        return True
    origin = typing.get_origin(annotation)
    if origin is None:
        return False
    # `Annotated[UploadFile, File()]`, `list[UploadFile]`, `X | None` — the
    # file type can sit at any depth of the hint.
    return any(_mentions_upload_file(arg) for arg in typing.get_args(annotation))


@functools.lru_cache(maxsize=None)
def endpoint_streams_files(endpoint: Callable[..., object] | None) -> bool:
    """Does this endpoint declare an `UploadFile` parameter?

    Read off the type hints rather than a list of paths: FastAPI itself
    decides "this is a file field" from the same hints, so the two cannot
    disagree. `None` (no route matched yet, or a body read before routing)
    gets the ordinary cap — the safe direction.
    """
    if endpoint is None:
        return False
    try:
        hints = typing.get_type_hints(endpoint, include_extras=True)
    except Exception:  # noqa: BLE001 — an unresolvable hint means "not an upload route"
        return False
    return any(_mentions_upload_file(t) for name, t in hints.items() if name != "return")


class BodySizeLimitMiddleware:
    """Reject request bodies over the cap that applies to their endpoint with a 413.

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
        ordinary = max_body_bytes()

        # Before routing the endpoint is unknown, so the declared length can
        # only be checked against the widest cap that COULD apply. A JSON
        # body labeled multipart gets past this line and is caught by the
        # count below the moment the login route reads it.
        widest = MULTIPART_MAX_BODY_BYTES if content_type.startswith("multipart/form-data") else ordinary
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > widest:
                    return await _reject(scope, send, widest)
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
        #
        # Its replacement was no better in the other direction. It ended the
        # body early with a clean, empty final chunk, so the route saw a
        # complete (short) body and RAN on it: a chunked `{"name": "X"}`
        # followed by a few MB of JSON whitespace parsed fine as its prefix,
        # the room was created and committed, and the client was told 413.
        # A client that then retried with a smaller body got a duplicate.
        #
        # So the over-limit read now FAILS — it raises — and the handler never
        # starts. FastAPI reads the whole body (JSON or multipart) before it
        # solves a single dependency or calls the handler, inside one `try`
        # that turns any failure of that read into an HTTP error response:
        # never a handler call, never the unhandled-exception path and its
        # durable row. Multipart parsing closes its spooled parts on any
        # exception, so a refused upload leaves nothing on disk either.
        #
        # What that `try` answers is a 400, though, not the 413 raised here:
        # the refusal travels up through `BaseHTTPMiddleware`'s receive
        # wrapper (the auth gate and the security headers are both one), which
        # reads inside an anyio task group, and the group re-raises it wrapped
        # in an `ExceptionGroup` — so FastAPI sees "the body could not be
        # read", not the `HTTPException` it would otherwise pass through. The
        # status is therefore corrected on the way out, at the
        # `http.response.start` boundary, before anything has been written.
        # That swap alone was the old mechanism; it only ever relabeled a
        # response. It is safe now because the read failing is what stops the
        # handler — the swap no longer stands between a committed write and a
        # client told otherwise.
        received = 0
        limit: int | None = None
        refused = False

        async def counting_receive() -> Message:
            nonlocal received, limit, refused
            if refused:
                # A reader that caught the first refusal and asked again gets
                # the same answer, never the rest of the body.
                raise _too_large()
            message = await receive()
            if message["type"] == "http.request":
                if limit is None:
                    # First read: the router has matched by now and put the
                    # endpoint on this same scope dict, so the cap can be the
                    # one that endpoint deserves.
                    limit = (
                        MULTIPART_MAX_BODY_BYTES
                        if endpoint_streams_files(scope.get("endpoint"))
                        else ordinary
                    )
                received += len(message.get("body", b""))
                if received > limit:
                    refused = True
                    logger.warning(
                        "Request body over the %d byte limit on %s %s — refused.",
                        limit, scope["method"], scope.get("path", ""),
                    )
                    raise _too_large()
            return message

        started = False

        async def refusing_send(message: Message) -> None:
            nonlocal started
            if refused:
                if not started:
                    started = True
                    await _reject(scope, send, limit or ordinary)
                return  # the app's own answer to a body it could not read
            await send(message)

        await self.app(scope, counting_receive, refusing_send)


def _too_large() -> HTTPException:
    # A fresh instance per raise: re-raising one shared exception object grows
    # its traceback chain for the life of the process (`routes/guest.py`'s
    # `_not_found` has the measurement).
    return HTTPException(status_code=413, detail="Request body too large")


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

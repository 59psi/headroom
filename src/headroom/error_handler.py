"""Make an unhandled error survive the request that produced it.

Until this existed, a 500 left exactly one trace: a stack trace on stdout,
inside a container, on a Pi. Nothing in the app could show it to you. The one
in-app error surface — "Recent Analysis Errors" and its nav badge — queries hats whose
`analysis_status` is `'error'`, so it covers photo analysis and nothing else:
not a route 500, not a lock storm, not a failed backup. A badge reading 0 was
an affirmative claim of general health that its own query could not support.

The activity log already has retention, an API, and a screen in Settings. One
handler is therefore all it takes to make application errors durable,
queryable and visible without SSH.

Deliberately re-raises. Starlette's `ServerErrorMiddleware` sends the response
this handler returns and then re-raises, so uvicorn still logs the traceback —
the log line is not replaced by the activity row, it is joined by one.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from headroom.utils.redaction import redact_share_tokens

logger = logging.getLogger(__name__)


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422, with the submitted value taken back out.

    Pydantic v2 puts the offending `input` into every validation error, and
    FastAPI serializes the list straight into the response body. For most
    fields that is a genuinely helpful 422. For `POST /api/auth/setup` it
    means a password rejected as too short is echoed back in clear text — into
    the browser's network tab, into any proxy log along the way, and into
    whatever the client does with an error body.

    A field name and a reason are what makes a 422 useful. The value is what
    the caller just sent; they have it.
    """
    errors = getattr(exc, "errors", lambda: [])()
    cleaned = [
        {k: v for k, v in err.items() if k not in ("input", "ctx", "url")}
        for err in errors
    ]
    return JSONResponse({"detail": cleaned}, status_code=422)


async def log_unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Record an `error.unhandled` activity row, then answer with a plain 500.

    The response carries a short correlation id and nothing else. An error id
    the user can read back to you is worth a great deal when the alternative
    is "it said something went wrong"; the exception text is not, and on this
    path it is exactly the kind of thing that leaks a filesystem path or a
    fragment of a query.
    """
    ref = uuid.uuid4().hex[:8]

    # Storing `path` instead of the full URL was chosen because "query strings
    # carry search terms and tokens". That reasoning is sound and it misses
    # this handler's own worst case: a share token is a PATH parameter, so for
    # `/api/public/share/{token}` the path IS the credential. Both sinks below
    # are durable — the activity row is in the database, which is what the
    # scheduled backup uploads off the box to a NAS or a cloud remote, so an
    # unredacted row puts a live bearer token in a third party's storage and
    # keeps it there for as long as that archive is retained.
    path = redact_share_tokens(request.url.path)

    # Its own session. The request's is very likely mid-rollback — it is often
    # the reason we are here — and a handler that raises while handling an
    # exception replaces a useful traceback with a useless one.
    #
    # Resolved through `app.state.session_factory`, the same handle the auth
    # gate uses, rather than importing `async_session` directly: that is the
    # seam the test suite swaps for its in-memory database, and a handler
    # bound to the module-level factory writes to the real one.
    try:
        from headroom.database import async_session
        from headroom.services.activity_service import log_activity

        factory = getattr(request.app.state, "session_factory", async_session)
        async with factory() as db:
            await log_activity(
                db,
                kind="error.unhandled",
                entity_type="system",
                entity_id=None,
                summary=f"{type(exc).__name__} on {request.method} {path} [{ref}]",
                details={
                    "ref": ref,
                    "method": request.method,
                    "path": path,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                },
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — best-effort; never mask the real error
        logger.exception("Failed to record unhandled error [%s]", ref)

    logger.error(
        "Unhandled error [%s] on %s %s: %s",
        ref, request.method, path, exc,
    )
    return JSONResponse(
        {"detail": "Internal server error", "ref": ref}, status_code=500
    )

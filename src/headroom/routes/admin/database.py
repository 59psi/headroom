"""Import a database: restore points on this server, staging, confirmation.

Two steps on purpose (see `services/database_import`): staging proves the
file and returns what it holds, which the card shows before anything live
changes; applying is a separate request carrying the staging token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request, Response

from headroom import limits
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.admin import (
    DatabaseImportPreview,
    DatabaseImportResult,
    RestorePointRead,
    RestorePointStage,
)
from headroom.services import database_import, errors

router = APIRouter(route_class=DomainErrorRoute)


@router.get("/database/restore-points", response_model=list[RestorePointRead])
async def list_restore_points():
    """Archives and database snapshots in `backups/`, newest first."""
    return await database_import.restore_points()


@router.get("/database/import", response_model=DatabaseImportPreview | None)
async def staged_import():
    """The import waiting for confirmation, if any — a reloaded card resumes it."""
    return database_import.staged()


async def _body(request: Request) -> AsyncIterator[bytes]:
    """The request body, with a failed read turned into a refusal.

    The read happens HERE, inside the handler — unlike a JSON or multipart
    route, whose body FastAPI reads before the handler runs. So an oversize
    body (the limit middleware raises from its receive) or a dropped upload
    (`ClientDisconnect`) would otherwise surface as an unhandled exception: a
    500 and a durable `error.unhandled` row for what is a refused upload. A
    domain error ends it as one; the middleware still answers 413 for the
    oversize case, because it corrects the status on the way out.
    """
    try:
        async for chunk in request.stream():
            yield chunk
    except Exception as exc:  # re-raised as a refusal: oversize, or the client went away
        raise errors.Invalid("The upload did not arrive in full.") from exc


@router.post("/database/import", response_model=DatabaseImportPreview)
@limits.streams_body(database_import.MAX_UPLOAD_BYTES)
async def stage_upload(
    request: Request,
    filename: str | None = Query(None, max_length=255, description="Shown in the preview only"),
):
    """Stage a backup archive or database file sent as the raw request body.

    Raw (`application/octet-stream`), not multipart: multipart parsing spools
    every part to `/tmp`, which is RAM under the shipped compose file, and a
    full archive is hundreds of megabytes. The body goes straight to the data
    volume instead.
    """
    declared = request.headers.get("content-length")
    return await database_import.stage_upload(
        _body(request),
        filename=filename,
        declared_size=int(declared) if declared and declared.isdigit() else None,
        session_factory=request.app.state.session_factory,
    )


@router.post("/database/import/restore-point", response_model=DatabaseImportPreview)
async def stage_restore_point(body: RestorePointStage, request: Request):
    """Stage one of the files `GET /database/restore-points` listed."""
    return await database_import.stage_restore_point(
        body.name, session_factory=request.app.state.session_factory
    )


@router.post("/database/import/{token}/apply", response_model=DatabaseImportResult)
async def apply_import(token: str, request: Request):
    """Replace the collection with the staged one. The live database is saved first.

    Takes the engine and sessions from `app.state` rather than a request
    session: the swap runs on its own connection, and a session this route
    held open would be one more reader of the rows being replaced.
    """
    return await database_import.apply(
        token,
        bind=request.app.state.engine,
        session_factory=request.app.state.session_factory,
    )


@router.delete("/database/import/{token}", status_code=204)
async def discard_import(token: str):
    """Drop a staged import without applying it. Idempotent."""
    await database_import.discard(token)
    return Response(status_code=204)

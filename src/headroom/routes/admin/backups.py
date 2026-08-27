"""On-demand backup download + scheduled-backup inventory."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.admin import (
    BackupHealthRead,
    BackupInfo,
    BackupUploadProvider,
    BackupUploadStatus,
    BackupUploadTestResult,
    BackupUploadUpdate,
)
from headroom.services import activity_service, backup_service, settings_service

router = APIRouter()


@router.get("/backup")
async def download_backup(
    include_uploads: bool = Query(True, description="Include uploads/ tree (photos)"),
    db: AsyncSession = Depends(get_db),
):
    """Stream a one-shot tar.gz of /data.

    `include_uploads=false` returns a DB-only snapshot — much smaller and
    much faster when the photo tree is large.
    """
    filename = backup_service.streaming_filename(include_uploads=include_uploads)
    # The backup tarball contains the whole DB (plaintext keys, tokens, session
    # ids, password hashes) — the single highest-value exfil artifact. Audit the
    # download so a full-dataset export is never invisible (S4/S10 — docs/AUDIT-HISTORY.md).
    await activity_service.log_activity(
        db, kind="backup.download", entity_type="system", entity_id=None,
        summary=f"Backup downloaded ({'full' if include_uploads else 'db-only'}): {filename}",
    )
    await db.commit()
    return StreamingResponse(
        backup_service.stream_backup(include_uploads=include_uploads),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backups/health", response_model=BackupHealthRead)
async def scheduled_backup_health(request: Request):
    """Is the scheduler working — not merely, is there a file on disk.

    Registered before `/backups/{...}`-shaped paths would matter, and distinct
    from the inventory endpoint on purpose: the inventory answers "what do I
    have", this answers "will I get another one".
    """
    h = backup_service.health()
    task = getattr(request.app.state, "backup_task", None)

    # Fall back to the newest backup's mtime when this process has not yet
    # recorded a run of its own. The in-memory record is process-local, and on
    # this deployment restarts are routine — so the endpoint named health was
    # the one that forgot, and a null here reads as "never succeeded" rather
    # than "not since boot". Flagged as derived rather than substituted
    # silently: a file proves a backup was written, not that anything is still
    # scheduled to write the next one.
    last_success, derived = h.last_success_at, False
    if last_success is None:
        last_success = await backup_service.newest_backup_at()
        derived = last_success is not None

    return BackupHealthRead(
        enabled=backup_service.backup_enabled(),
        # A cancelled/finished task means no further backups will be written,
        # whatever the last attempt's outcome was.
        running=task is not None and not task.done(),
        last_attempt_at=h.last_attempt_at,
        last_success_at=last_success,
        last_success_derived=derived,
        last_error=h.last_error,
        last_skip_reason=h.last_skip_reason,
        consecutive_failures=h.consecutive_failures,
    )


@router.get("/backups", response_model=list[BackupInfo])
async def list_scheduled_backups():
    """Inventory of on-disk scheduled backups, newest first."""
    paths = await backup_service.list_backups()
    return [
        BackupInfo(
            filename=p.name,
            size_bytes=p.stat().st_size,
            # tz-aware, like `backup_service.newest_backup_at()`, which reads
            # this same `st_mtime`. A naive value here made the file list and
            # the health card disagree by the host's UTC offset.
            created_at=datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc),
        )
        for p in paths
    ]


# ---- off-box upload -------------------------------------------------- #
#
# Registered before any `/backups/{...}` path would shadow them, same reason
# `/backups/health` is.
#
# There is deliberately NO endpoint that accepts a command. The browser sends
# a provider name and a destination; the argv is assembled from a template
# this app owns (`backup_service.UPLOAD_PROVIDERS`), so no combination of
# input can change the binary, add a flag, or reach a shell. That matters more
# than usual here: whatever this configures runs unattended, as the app user,
# after every backup.


async def _upload_status(db: AsyncSession) -> BackupUploadStatus:
    h = backup_service.health()
    env_cmd = backup_service.backup_upload_cmd()
    provider = await settings_service.get_setting(
        db, backup_service.UPLOAD_PROVIDER_KEY
    )
    destination = await settings_service.get_setting(
        db, backup_service.UPLOAD_DESTINATION_KEY
    )
    return BackupUploadStatus(
        configured=bool(env_cmd) or bool(provider and destination),
        provider=provider,
        destination=destination,
        from_environment=bool(env_cmd),
        available_providers=[
            BackupUploadProvider(
                name=p.name,
                label=p.label,
                destination_hint=p.destination_hint,
                example=p.example,
                setup=list(p.setup),
                secret_env=p.secret_env,
                binary=p.binary,
                # Resolved per request rather than cached. rclone arrives by a
                # bind mount, so it can appear or vanish between restarts
                # without anything in this process changing; rsync and ssh ship
                # in the image and only change when it is rebuilt.
                binary_available=backup_service.provider_binary_available(p.name) or False,
            )
            for p in sorted(backup_service.UPLOAD_PROVIDERS.values(), key=lambda p: p.label)
        ],
        binary_available=backup_service.provider_binary_available(provider or ""),
        last_upload_at=h.last_upload_at,
        last_upload_ok=h.last_upload_ok,
        last_upload_error=h.last_upload_error,
        last_upload_name=h.last_upload_name,
        upload_successes=h.upload_successes,
        upload_failures=h.upload_failures,
    )


@router.get("/backups/upload", response_model=BackupUploadStatus)
async def get_backup_upload(db: AsyncSession = Depends(get_db)):
    """Is an off-box copy configured, and is it working?

    The most consequential unknown on a single-box deployment: local rolling
    backups on the same card protect against corruption, not against the card.
    """
    return await _upload_status(db)


@router.put("/backups/upload", response_model=BackupUploadStatus)
async def set_backup_upload(
    data: BackupUploadUpdate, db: AsyncSession = Depends(get_db)
):
    from fastapi import HTTPException  # noqa: PLC0415

    # No membership check here: `validate_destination` already rejects an
    # unknown provider with the same message, and stating it twice is two
    # places for the wording — and the list of providers — to drift apart.
    try:
        destination = backup_service.validate_destination(data.destination, data.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    await settings_service.set_setting(
        db, backup_service.UPLOAD_PROVIDER_KEY, data.provider
    )
    await settings_service.set_setting(
        db, backup_service.UPLOAD_DESTINATION_KEY, destination
    )
    await activity_service.log_activity(
        db, kind="backup.upload_configured", entity_type="system", entity_id=None,
        summary=f"Off-box backup upload set to {data.provider} → {destination}",
    )
    await db.commit()
    return await _upload_status(db)


@router.delete("/backups/upload", response_model=BackupUploadStatus)
async def clear_backup_upload(db: AsyncSession = Depends(get_db)):
    await settings_service.set_setting(db, backup_service.UPLOAD_PROVIDER_KEY, "")
    await settings_service.set_setting(db, backup_service.UPLOAD_DESTINATION_KEY, "")
    await activity_service.log_activity(
        db, kind="backup.upload_cleared", entity_type="system", entity_id=None,
        summary="Off-box backup upload turned off",
    )
    await db.commit()
    return await _upload_status(db)


@router.post("/backups/upload/test", response_model=BackupUploadTestResult)
async def test_backup_upload(db: AsyncSession = Depends(get_db)):
    """Actually run the configured upload against the newest backup.

    The whole point of the feature is that it works unattended, which means
    nobody finds out it is broken until the day they need it. A button that
    performs the real thing — same argv, same binary, same credentials — is
    the only check worth having; a dry run would prove the form was filled in.
    """
    backups = await backup_service.list_backups()
    if not backups:
        return BackupUploadTestResult(
            ok=False,
            detail="No backup on disk to upload yet. One is written after the next change.",
        )
    argv = await backup_service.resolve_upload_argv(db, backups[0])
    if not argv:
        return BackupUploadTestResult(ok=False, detail="No off-box upload is configured.")
    # Say which of the two it is. "No such file or directory" from a subprocess
    # is a true statement about argv[0] that reads as a problem with the
    # destination, and the fix — mount the binary, use the matching compose
    # overlay — is nowhere in that message.
    if not backup_service.binary_available(argv[0]):
        return BackupUploadTestResult(
            ok=False,
            detail=(
                f"'{argv[0]}' is not available inside the container, so no upload "
                "can run. rsync and ssh ship in the image, so a missing one means "
                "the image predates 2.46 — rebuild. rclone is bind-mounted, so a "
                "missing one means docker-compose.backup-rclone.yml is not in "
                "your compose command."
            ),
        )

    before = backup_service.health().upload_failures
    await backup_service._run_upload_hook(backups[0], argv=argv)
    h = backup_service.health()
    ok = h.upload_failures == before and h.last_upload_ok is True
    if ok:
        return BackupUploadTestResult(
            ok=True, detail=f"Uploaded {backups[0].name} with {argv[0]}."
        )
    detail = _explain(h.last_upload_error or "Upload failed — see the container log.")

    # "Unknown module" is a dead end on its own, and the real list is
    # install-specific — DSM derives modules from your shared folders. This
    # container has GNU rsync, so it asks rather than telling the operator to go
    # and run a command themselves.
    if "unknown module" in detail.lower():
        destination = await settings_service.get_setting(
            db, backup_service.UPLOAD_DESTINATION_KEY
        )
        modules = await backup_service.list_rsync_modules(destination or "")
        if modules:
            detail += "\n\nThat host currently offers: " + ", ".join(modules)
        else:
            detail += (
                "\n\nCould not list its modules either — the daemon may not be "
                "reachable from this container."
            )

    return BackupUploadTestResult(ok=False, detail=detail)


#: Failures whose message is accurate but whose CAUSE is somewhere else, mapped
#: to the thing to actually go and do. Relaying rsync's own words is correct but
#: not always enough — an operator reading "Unknown module" has no way to know
#: that DSM has two rsync checkboxes and only one of them defines modules.
_FAILURE_HINTS: tuple[tuple[str, str], ...] = (
    (
        "unknown module",
        "The daemon answered but has no module by that name. On a Synology, tick "
        "Control Panel → File Services → rsync → **Enable network backup "
        "service** — NOT 'Enable rsync service', which is rsync over SSH and "
        "defines no modules. Run `rsync USER@HOST::` to list what it does offer. "
        "Module names resolve BEFORE the password, so this is not a credentials "
        "problem.",
    ),
    (
        "auth failed",
        "The module exists but the rsync account or password was rejected. That "
        "account is separate from your DSM login, and the password comes from "
        "HEADROOM_BACKUP_RSYNC_PASSWORD in the host's .env.",
    ),
    (
        "connection refused",
        "Nothing is listening on the rsync port. Check the service is enabled and "
        "that port 873 is open on the NAS firewall.",
    ),
    (
        "permission denied",
        "Reached the destination but could not write. For rsync over SSH, check "
        "the key is authorized and the path exists; the container runs as uid 1000.",
    ),
)


def _explain(error: str) -> str:
    """Append guidance for failures whose real cause is elsewhere."""
    lowered = error.lower()
    for needle, hint in _FAILURE_HINTS:
        if needle in lowered:
            return f"{error}\n\n{hint}"
    return error

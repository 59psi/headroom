"""Import a database: put a backup's collection in place of this one.

Until this existed the only way back to a backup was the recipe in
OPERATIONS §4 — stop the stack, delete the WAL sidecar by hand, untar over the
volume with a one-off container, start again — which is a terminal on the Pi,
not a phone, and gets one step wrong in the way that matters: forget the WAL
and SQLite folds the post-backup writes back into the "restored" file. The
snapshots the app takes itself (`pre-upgrade-*.db`, and now `pre-import-*.db`)
had no way back at all short of that recipe.

**Two steps, and nothing live changes in the first.** `stage_*` takes a file —
an upload, a restore point on this server, or a path (the command line) —
proves it is a readable Headroom database, brings a COPY of it up to this
version with the same `database_upgrade.upgrade` the boot runs, and returns
what it holds. That preview is what the confirm dialog shows. `apply` then:

1. refuses while a photo is being analyzed, re-cut or imported — by the
   worker or inside a request — since a write to hat #12 must not land on a
   different hat #12;
2. restores the archive's photos BEFORE the rows that point at them (photo
   names are UUIDs, so a photo landing early is an unreferenced file, never a
   wrong one) — never deleting or overwriting a file already there;
3. takes the database's write lock, and only then saves the live database as
   `backups/pre-import-<time>.db` (fsynced): with no other writer able to
   commit, the copy is exactly what is replaced — nothing written in between
   is in neither. It is itself a restore point, so every import can be undone
   the way it was done, and nothing is imported if it cannot be written;
4. swaps the rows in that same transaction on the app's own engine: the
   staged file is `ATTACH`ed and every table is emptied and refilled from it.
   Every pooled connection sees the old collection or the new one, never a
   mix, and no database file is replaced underneath a connection that has it
   open — the reason this is not a file copy.

The command line (`headroom.import_database`) adds one more guard: it holds
the data directory's `instance_lock`, which the app holds while it runs.

**What an import keeps.** It replaces the COLLECTION — hats, cases, rooms,
colors, wear, purchases, history. This install's ACCESS stays as it is: the
account (you stay signed in, with the password you have now), passkeys,
sessions and share links — a backup from before a link was revoked must not
bring the link back — plus the guest-view switch and this server's CA
fingerprint. So do its keys, model and off-site upload, exactly as they are
(set or not: see `_INSTALL_KEYS`); a few harmless preferences it never set
are filled in from the import. A database with no account yet (the command
line on a fresh install) takes the import's account and settings too.

**Numbers never go backwards.** Hat ids and case numbers are printed on
stickers (`/t/h/<id>`, `/t/c/<display id>`), and both are promised never to be
reissued. Restoring an older backup would otherwise hand the next new hat the
id of one created after the backup — whose sticker is still on a shelf. The
AUTOINCREMENT high-water marks and the released case numbers are therefore
the larger of the two databases', with the live cases' numbers counted as
released.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import re
import secrets
import shutil
import sqlite3
import tarfile
import time
import zlib
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path, PurePosixPath

from sqlalchemy import column, delete, func, insert, select, table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from headroom.config import settings
from headroom.database import Base
from headroom.models import (
    AppSetting,
    AuthSession,
    Case,
    Hat,
    ImportJob,
    PasskeyCredential,
    ShareLink,
    User,
)
from headroom.schemas.admin import (
    DatabaseImportPreview,
    DatabaseImportResult,
    ImportSourceKind,
    RestorePointKind,
    RestorePointRead,
)
from headroom.services import (
    activity_service,
    analysis_queue,
    auth_service,
    backup_service,
    ca_vault,
    capacity,
    case_service,
    database_upgrade,
    ebay_service,
    errors,
    guest_view_service,
    hat_analysis_pipeline,
    hat_service,
    import_service,
    locks,
    settings_service,
    upgrade_guard,
)
from headroom.utils import branding, disk
from headroom.utils.paths import safe_join

logger = logging.getLogger(__name__)

#: The undo point every import writes first, beside the scheduled archives.
SNAPSHOT_PREFIX = "pre-import-"
#: Kept. Each is a whole database (about a megabyte here), so this is cheap —
#: but unbounded, a habit of importing would be a slow leak on an SD card.
KEEP_SNAPSHOTS = 5
#: The largest upload accepted. Ten times a full archive of this collection
#: today (~200 MB with every photo); the free-space check below is the bound
#: that usually decides.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
#: Left free on the data volume after an upload or a photo restore — the
#: database, the backups and the next photo all live there too.
FREE_SPACE_MARGIN_BYTES = 256 * 1024 * 1024
#: How long a staged import waits for its confirmation.
STAGE_TTL_SECONDS = 60 * 60

_SQLITE_MAGIC = b"SQLite format 3\x00"
_GZIP_MAGIC = b"\x1f\x8b"
#: The upload subtrees an archive may restore. Anything else under
#: `data/uploads/` is ignored rather than written somewhere the app never reads.
_PHOTO_DIRS = ("hats", "branding")
#: The image extensions an upload may carry (`photo.validate_image_content_type`
#: admits these types; `generate_filename` keeps the upload's suffix).
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")
#: Exactly the files the app writes, and nothing else, may be restored from an
#: archive: a uuid4-hex photo in `hats/`, its WebP thumbnail and export
#: derivative, and the site logo. Any other file in an archive is ignored.
_RESTORABLE = re.compile(
    r"hats/(?:(?:thumbs|export)/[0-9a-f]{32}\.webp"
    r"|[0-9a-f]{32}(?:" + "|".join(re.escape(s) for s in _IMAGE_SUFFIXES) + r"))"
    r"|branding/logo(?:" + "|".join(re.escape(s) for s in branding.LOGO_SUFFIXES) + r")"
)
_COPY_CHUNK = 1024 * 1024

#: Tables that are this install's access, not the collection (see module doc).
_ACCOUNT_TABLES = frozenset({
    User.__tablename__,
    AuthSession.__tablename__,
    PasskeyCredential.__tablename__,
    ShareLink.__tablename__,
})
#: Settings that describe THIS server whatever the import holds: the live
#: value, or none at all. A CA fingerprint from another install would raise
#: a false "your certificate authority changed" alarm.
_SERVER_KEYS = frozenset({ca_vault.ROOT_FINGERPRINT_KEY})
#: This install's access and configuration, kept like the account tables:
#: the live row or none — taken from the import only when there is no account
#: here to keep (a fresh install restored from the command line).
#:
#: "Live row or none", not "live row, else the import's": several of these can
#: be set by ENVIRONMENT, which `settings_service.get_key` reads only when the
#: database has no row — so an imported row would silently outrank a key this
#: server was deliberately configured with. And a value the owner removed (an
#: off-site destination, a revoked key) must stay removed, not come back from
#: a backup older than the removal.
_INSTALL_KEYS = frozenset({
    auth_service.SETUP_SENTINEL_KEY,
    guest_view_service.GUEST_VIEW_KEY,
    settings_service.ANTHROPIC_KEY.setting_key,
    settings_service.GOOGLE_VISION_KEY.setting_key,
    settings_service.ANTHROPIC_MODEL_NAME,
    ebay_service.EBAY_APP_ID.setting_key,
    ebay_service.EBAY_CERT_ID.setting_key,
    backup_service.UPLOAD_PROVIDER_KEY,
    backup_service.UPLOAD_DESTINATION_KEY,
})


class SettingPolicy(StrEnum):
    """How an import treats one `app_settings` key."""

    #: The live value, or none at all.
    keep = "keep"
    #: The import's value.
    imported = "import"
    #: The live value when this install has one, else the import's.
    prefer_live = "prefer_live"


def _collection_keys() -> frozenset[str]:
    """Settings that are the collection's own history: always the import's.

    Derived from the code that writes them, so a new one-time repair is
    covered without anyone remembering this list. Case numbering is handled
    separately (it takes the larger of both).
    """
    return frozenset(
        {flag for flag, _, _ in database_upgrade.ONE_TIME_REPAIRS}
        | {upgrade_guard.LAST_BOOTED_KEY}
    )


def setting_policy(key: str, *, keep_account: bool) -> SettingPolicy:
    """The policy for one key. `prefer_live` covers the tag address, the eBay
    marketplace — harmless preferences, filled in for an install that never
    set them — and is the default: a setting nobody classified is far more
    likely to be configuration than collection."""
    if key in _SERVER_KEYS:
        return SettingPolicy.keep
    if key in _INSTALL_KEYS:
        return SettingPolicy.keep if keep_account else SettingPolicy.imported
    if key in _collection_keys():
        return SettingPolicy.imported
    return SettingPolicy.prefer_live


# --------------------------------------------------------------------------
# restore points
# --------------------------------------------------------------------------


def _restore_point_kind(name: str) -> RestorePointKind | None:
    """What a file in `backups/` is, or None if it is not one to restore."""
    if backup_service.is_archive_name(name):
        return RestorePointKind.archive
    if not name.endswith(".db"):
        return None
    if name.startswith(upgrade_guard.SNAPSHOT_PREFIX):
        return RestorePointKind.pre_upgrade
    if name.startswith(SNAPSHOT_PREFIX):
        return RestorePointKind.pre_import
    return RestorePointKind.snapshot


def _restore_points_sync() -> list[RestorePointRead]:
    found: list[RestorePointRead] = []
    for path in backup_service.backup_dir().iterdir():
        # Dotfiles are the scheduler's bookkeeping and `.spool/`; `.partial`
        # files are writes in progress and are neither kind of name.
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            continue
        kind = _restore_point_kind(path.name)
        if kind is None:
            continue
        st = path.stat()
        found.append(RestorePointRead(
            name=path.name,
            kind=kind,
            size_bytes=st.st_size,
            created_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        ))
    found.sort(key=lambda p: p.created_at, reverse=True)
    return found


async def restore_points() -> list[RestorePointRead]:
    """Archives and database copies in `backups/`, newest first."""
    return await asyncio.to_thread(_restore_points_sync)


# --------------------------------------------------------------------------
# staging
# --------------------------------------------------------------------------


@dataclass
class _StagedImport:
    """The import waiting for its confirmation, and where its files are."""

    preview: DatabaseImportPreview
    spool: Path
    database: Path
    archive: Path | None
    #: (member name in the archive, path relative to the upload dir)
    photos: list[tuple[str, str]] = field(default_factory=list)
    photo_bytes: int = 0
    expires: float = 0.0


@dataclass
class _Unpacked:
    raw_db: Path
    archive: Path | None
    photos: list[tuple[str, str]]
    photo_bytes: int
    degraded: bool


#: The one staged import. Single-owner app: staging a second file replaces the
#: first, so an abandoned preview costs one spool directory, never a pile.
_waiting: _StagedImport | None = None
#: Post-import work (thumbnail and export backfills) — held so a task is never
#: garbage-collected mid-run, and so a test can wait for it.
_background: set[asyncio.Task] = set()


def _mb(n: int) -> str:
    return f"{max(n, 0) // (1024 * 1024):,} MB"


def _room(path: Path) -> int | None:
    """Bytes that may be written on the data volume, or None if it can't say."""
    status = disk.check(path)
    return None if status.error else status.free_bytes - FREE_SPACE_MARGIN_BYTES


def _upload_room(spool: Path) -> int:
    """The most an upload may be: the cap, or less when space is short."""
    room = _room(spool)
    # Space unknown: fall back to the hard cap rather than refusing.
    return MAX_UPLOAD_BYTES if room is None else min(MAX_UPLOAD_BYTES, room)


def _too_big(size: int, room: int) -> str:
    return (
        f"That file is {_mb(size)} and there is room for {_mb(room)} "
        "on the data volume (keeping some free for the app itself)."
    )


async def _receive(chunks: AsyncIterable[bytes], target: Path, declared: int | None) -> None:
    """Stream an upload to `target`, bounded by the cap and the free space.

    Straight to the data volume, never `/tmp`: under the shipped compose file
    `/tmp` is RAM, inside the container's 1 GB limit, and a full archive is
    ~200 MB and growing. Written in 1 MB slices off the event loop.
    """
    room = await asyncio.to_thread(_upload_room, target.parent)
    if declared is not None and declared > room:
        raise errors.Invalid(_too_big(declared, room))
    written = 0
    pending = bytearray()
    with target.open("wb") as out:
        async for chunk in chunks:
            written += len(chunk)
            if written > room:
                raise errors.Invalid(_too_big(written, room))
            pending += chunk
            if len(pending) >= _COPY_CHUNK:
                await asyncio.to_thread(out.write, bytes(pending))
                pending.clear()
        if pending:
            await asyncio.to_thread(out.write, bytes(pending))
    if written == 0:
        raise errors.Invalid("The upload was empty.")


def _plain_parts(parts: tuple[str, ...]) -> bool:
    """No empty, `.` or `..` part and no backslash: a path that stays put."""
    return not any(p in ("", ".", "..") or "\\" in p for p in parts)


def _member_parts(name: str) -> tuple[str, ...] | None:
    """An archive member's path parts, or None unless it is a plain `data/…` path.

    Also skips macOS AppleDouble `._*` files (a backup re-packed with Finder's
    `tar` carries `data/._headroom.db`, which is not a database). Extraction
    never uses the member's own path anyway — files are written to paths this
    module builds — so this is about what to READ.
    """
    path = PurePosixPath(name)
    parts = path.parts
    if path.is_absolute() or len(parts) < 2 or parts[0] != "data":
        return None
    if not _plain_parts(parts) or any(p.startswith("._") for p in parts):
        return None
    return parts


def _unpack_archive_sync(archive: Path, raw_dir: Path) -> _Unpacked:
    """Pull the database out of a backup archive and list its photos.

    One streaming pass; photos are only listed here and written at apply time.
    A database written by the raw-file fallback comes with its `-wal`, which is
    extracted beside it under the matching name so SQLite replays it on open.
    """
    databases: list[str] = []
    photos: list[tuple[str, str]] = []
    photo_bytes = 0
    degraded = False
    # A member's declared size is the most tar will write for it, so checking
    # it first bounds the extraction by the room left on the data volume.
    room = _upload_room(raw_dir)
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                parts = _member_parts(member.name)
                if parts is None or not member.isfile():
                    continue
                if len(parts) == 2:
                    leaf = parts[1]
                    if leaf.endswith((".db", ".db-wal")):
                        if member.size > room:
                            raise errors.Invalid(_too_big(member.size, room))
                        room -= member.size
                        source = tar.extractfile(member)
                        if source is None:
                            continue
                        with source, (raw_dir / leaf).open("wb") as out:
                            shutil.copyfileobj(source, out, _COPY_CHUNK)
                        if leaf.endswith(".db"):
                            databases.append(leaf)
                    elif leaf == "DEGRADED-BACKUP-README.txt":
                        degraded = True
                elif len(parts) >= 4 and parts[1] == "uploads" and parts[2] in _PHOTO_DIRS:
                    rel = "/".join(parts[2:])
                    if _RESTORABLE.fullmatch(rel):
                        photos.append((member.name, rel))
                        photo_bytes += member.size
    except (tarfile.TarError, EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise errors.Invalid(
            f"That archive could not be read ({exc}). Is the download complete?"
        ) from exc
    if "headroom.db" in databases:
        chosen = "headroom.db"
    elif len(databases) == 1:
        chosen = databases[0]
    elif databases:
        raise errors.Invalid(
            "That archive holds more than one database "
            f"({', '.join(sorted(databases))}) and none is data/headroom.db."
        )
    else:
        raise errors.Invalid("That archive has no database in it. Is it a Headroom backup?")
    return _Unpacked(raw_dir / chosen, archive, photos, photo_bytes, degraded)


def _unpack_sync(source: Path, spool: Path) -> _Unpacked:
    """A private copy of the source's database, whatever shape it arrived in."""
    raw_dir = spool / "raw"
    raw_dir.mkdir()
    with source.open("rb") as fh:
        head = fh.read(len(_SQLITE_MAGIC))
    if head.startswith(_GZIP_MAGIC):
        return _unpack_archive_sync(source, raw_dir)
    if head == _SQLITE_MAGIC:
        # Copied, never opened in place: opening a file in WAL mode writes
        # beside it, and the source may be a snapshot that has to stay exactly
        # what it is. A `-wal` next to it holds commits not yet folded in, so
        # it travels too.
        raw = raw_dir / "incoming.db"
        shutil.copyfile(source, raw)
        wal = source.with_name(source.name + "-wal")
        if wal.is_file():
            shutil.copyfile(wal, raw_dir / "incoming.db-wal")
        return _Unpacked(raw, None, [], 0, False)
    raise errors.Invalid(
        "That is not a Headroom backup (.tar.gz) or database (.db) file."
    )


def _check_database_sync(raw: Path, dest: Path) -> str | None:
    """Prove `raw` is a sound Headroom database; write a clean copy to `dest`.

    Returns the version that last ran it. `VACUUM INTO` folds any WAL in and
    writes one self-contained file, the same way the backups are taken.
    """
    try:
        conn = sqlite3.connect(raw)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                raise errors.Invalid(
                    "That database is damaged. SQLite's integrity check says: "
                    f"{row[0] if row else 'nothing'}"
                )
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not {"hats", "cases"} <= tables:
                raise errors.Invalid(
                    "That is a SQLite database, but not a Headroom one: it has no hats table."
                )
            version = None
            if "app_settings" in tables:
                found = conn.execute(
                    "SELECT value FROM app_settings WHERE key = ?", (upgrade_guard.LAST_BOOTED_KEY,)
                ).fetchone()
                version = found[0] if found else None
            conn.execute("VACUUM INTO ?", (str(dest),))
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise errors.Invalid(f"That file is not a readable database ({exc}).") from exc
    return version


def _photo_path_ok(value: str) -> bool:
    """A path the app could have written: relative, under `hats/`, an image."""
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and len(path.parts) >= 2
        and path.parts[0] == "hats"
        and _plain_parts(path.parts)
        and path.suffix.lower() in _IMAGE_SUFFIXES
    )


def _check_photo_paths_sync(db: Path) -> None:
    """Refuse a database whose photo paths are not ones the app writes.

    The app only ever writes relative image paths under `hats/` here. A
    database holding anything else was not written by Headroom, so the whole
    import is refused before anything else runs on it.
    """
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT id, photo_path, original_path, thumb_path FROM hats"
        ).fetchall()
    finally:
        conn.close()
    for hat_id, *paths in rows:
        for value in paths:
            if value and not _photo_path_ok(value):
                raise errors.Invalid(
                    f"That database points hat #{hat_id}'s photo at {value!r}, outside "
                    "the photo folder — Headroom never writes a path like that, so this "
                    "file was not written by it. Nothing was imported."
                )


def _version_key(version: str | None) -> tuple[int, int, int] | None:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def _refuse_newer(version: str | None) -> None:
    """A database a NEWER Headroom has run may hold what this one cannot read."""
    running = upgrade_guard.running_version()
    theirs, ours = _version_key(version), _version_key(running)
    if theirs and ours and theirs > ours:
        raise errors.Invalid(
            f"That database was last used by Headroom {version}, newer than this "
            f"server's {running}. Upgrade this server first, then import it."
        )


async def _upgrade_copy(staged_db: Path) -> None:
    """Migrate and repair the staged copy exactly as a boot would the live one."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{staged_db}", echo=False, hide_parameters=True
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await database_upgrade.upgrade(engine, factory, snapshot=False)
    except errors.DomainError:
        raise
    except Exception as exc:  # a refusal, re-raised as one
        logger.exception("Could not bring an imported database up to this version")
        # The driver's own message, first line only: SQLAlchemy appends the
        # statement and a docs link, which is log material, not an answer.
        reason = str(getattr(exc, "orig", None) or exc).splitlines()[0]
        raise errors.Invalid(
            f"That database could not be brought up to this version of Headroom ({reason})."
        ) from exc
    finally:
        await engine.dispose()


def _parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _count_sync(db: Path, unpacked: _Unpacked) -> dict:
    """What the staged database holds, for the preview."""
    conn = sqlite3.connect(db)
    try:
        def count(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]

        counts = {
            "hats": count("SELECT COUNT(*) FROM hats WHERE disposed_at IS NULL"),
            "disposed_hats": count("SELECT COUNT(*) FROM hats WHERE disposed_at IS NOT NULL"),
            "cases": count("SELECT COUNT(*) FROM cases"),
            "rooms": count("SELECT COUNT(*) FROM rooms"),
            "purchases": count("SELECT COUNT(*) FROM purchases"),
            "wear_logs": count("SELECT COUNT(*) FROM wear_log"),
            "newest_change_at": _parse_stamp(
                conn.execute("SELECT MAX(updated_at) FROM hats").fetchone()[0]
            ),
        }
        photo_paths = [
            r[0] for r in conn.execute(
                "SELECT photo_path FROM hats WHERE photo_path IS NOT NULL AND photo_path != ''"
            )
        ]
    finally:
        conn.close()
    in_archive = {rel for _, rel in unpacked.photos}
    missing = 0
    for rel in photo_paths:
        if rel in in_archive:
            continue
        on_disk = safe_join(settings.upload_dir, rel)
        if on_disk is None or not on_disk.is_file():
            missing += 1
    # Main photos only (not thumbnails), so the number reads as "photos".
    counts["photos_included"] = sum(
        1 for _, rel in unpacked.photos
        if rel.count("/") == 1 and rel.startswith("hats/")
    )
    counts["photos_missing"] = missing
    return counts


async def _stage_source(
    source: Path,
    spool: Path,
    *,
    name: str,
    from_server: bool,
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> DatabaseImportPreview:
    """Validate, migrate and summarize `source`; make it the waiting import."""
    global _waiting
    unpacked = await asyncio.to_thread(_unpack_sync, source, spool)
    staged_db = (spool / "incoming.db").resolve()
    version = await asyncio.to_thread(_check_database_sync, unpacked.raw_db, staged_db)
    await asyncio.to_thread(shutil.rmtree, spool / "raw", True)
    _refuse_newer(version)
    await asyncio.to_thread(_check_photo_paths_sync, staged_db)
    await _upgrade_copy(staged_db)
    counts = await asyncio.to_thread(_count_sync, staged_db, unpacked)
    current, keeps_account = 0, False
    if session_factory is not None:
        async with session_factory() as db:
            current = (await db.execute(
                select(func.count(Hat.id)).where(Hat.disposed_at.is_(None))
            )).scalar_one()
            keeps_account = await auth_service.user_count(db) > 0
    preview = DatabaseImportPreview(
        token=secrets.token_urlsafe(18),
        source=name,
        from_server=from_server,
        kind=ImportSourceKind.archive if unpacked.archive is not None else ImportSourceKind.database,
        version=version,
        degraded=unpacked.degraded,
        current_hats=current,
        keeps_account=keeps_account,
        **counts,
    )
    previous, _waiting = _waiting, _StagedImport(
        preview=preview,
        spool=spool,
        database=staged_db,
        archive=unpacked.archive,
        photos=unpacked.photos,
        photo_bytes=unpacked.photo_bytes,
        expires=time.monotonic() + STAGE_TTL_SECONDS,
    )
    if previous is not None:
        await asyncio.to_thread(backup_service.close_spool_sync, previous.spool)
    logger.info(
        "Staged an import of %s: %d hats (%s)", name, preview.hats, version or "version unknown"
    )
    return preview


async def _in_new_spool(
    build: Callable[[Path], Awaitable[DatabaseImportPreview]],
) -> DatabaseImportPreview:
    """Run `build(spool)` in a fresh spool; drop the spool if it fails."""
    spool = await asyncio.to_thread(backup_service.open_spool_sync, "headroom-import-")
    try:
        return await build(spool)
    except BaseException:
        # Unclaimed first and without I/O, so even a cancellation landing on
        # the deletion leaves it to the next sweep (see `backup_service`).
        backup_service.release_spool(spool)
        await asyncio.shield(asyncio.to_thread(shutil.rmtree, spool, True))
        raise


async def stage_upload(
    chunks: AsyncIterable[bytes],
    *,
    filename: str | None,
    declared_size: int | None,
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> DatabaseImportPreview:
    """Stage a file sent as a stream: the browser's raw request body, or stdin."""
    name = Path(filename or "").name[:200] or "uploaded file"

    async def build(spool: Path) -> DatabaseImportPreview:
        target = spool / "upload"
        await _receive(chunks, target, declared_size)
        return await _stage_source(
            target, spool, name=name, from_server=False, session_factory=session_factory
        )

    return await _in_new_spool(build)


async def stage_restore_point(
    name: str, *, session_factory: async_sessionmaker[AsyncSession] | None
) -> DatabaseImportPreview:
    """Stage a backup or database copy already on this server, by its listed name.

    Looked up in the listing rather than joined onto a path, so a name can
    only ever be one of the files the card showed.
    """
    if name not in {p.name for p in await restore_points()}:
        raise errors.NotFound("There is no backup by that name on this server.")
    source = backup_service.backup_dir() / name

    async def build(spool: Path) -> DatabaseImportPreview:
        return await _stage_source(
            source, spool, name=name, from_server=True, session_factory=session_factory
        )

    return await _in_new_spool(build)


async def stage_file(
    path: Path, *, session_factory: async_sessionmaker[AsyncSession] | None
) -> DatabaseImportPreview:
    """Stage a file by path — the command line's door.

    `session_factory=None`: there is no live database to compare against yet
    (a preview on a fresh install), and opening one would create it.
    """
    if not path.is_file():
        raise errors.NotFound(f"No such file: {path}")

    async def build(spool: Path) -> DatabaseImportPreview:
        return await _stage_source(
            path, spool, name=path.name, from_server=False, session_factory=session_factory
        )

    return await _in_new_spool(build)


def waiting() -> DatabaseImportPreview | None:
    """The import waiting for confirmation, if it has not expired."""
    current = _waiting
    if current is None or time.monotonic() > current.expires:
        return None
    return current.preview


async def discard(token: str | None = None) -> bool:
    """Drop the waiting import (only if it is `token`'s, when one is given)."""
    global _waiting
    current = _waiting
    if current is None or (token is not None and current.preview.token != token):
        return False
    _waiting = None
    await asyncio.to_thread(backup_service.close_spool_sync, current.spool)
    return True


# --------------------------------------------------------------------------
# applying
# --------------------------------------------------------------------------


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def busy_reason(db: AsyncSession) -> str | None:
    """Why an import must wait, or None.

    Only work something is actually doing counts: a hat left `pending` while
    no worker runs is stranded, not in progress, and the import's own
    re-queue (or the next boot) picks it up. Counting it would block every
    import until a restart, for nothing. With no worker, a request runs the
    pipeline itself, and those runs are counted where they happen
    (`analysis_queue.running_inline`).
    """
    inline = analysis_queue.inline_running()
    if inline:
        return f"{_plural(inline, 'photo')} still being analyzed"
    if analysis_queue.worker_alive():
        pending = (await db.execute(
            select(func.count(Hat.id)).where(Hat.analysis_status == analysis_queue.PENDING)
        )).scalar_one()
        if pending:
            return f"{_plural(pending, 'photo')} still being analyzed"
        cutting = (await db.execute(
            select(func.count(Hat.id)).where(hat_analysis_pipeline.recut_in_progress())
        )).scalar_one()
        if cutting:
            return f"{_plural(cutting, 'photo')} still being cut out"
    if import_service.worker_alive():
        active = (await db.execute(
            select(func.count(ImportJob.id)).where(ImportJob.status.in_(("queued", "running")))
        )).scalar_one()
        if active:
            return f"{_plural(active, 'photo import')} still running"
    return None


async def _refuse_if_busy(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as db:
        reason = await busy_reason(db)
    if reason:
        raise errors.Conflict(
            f"Not now: {reason}. Try again when it finishes, so nothing is "
            "written to a hat that is about to be replaced."
        )


def _undo_copy_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return backup_service.backup_dir() / f"{SNAPSHOT_PREFIX}{stamp}.db"


def _undo_copy_failed(exc: Exception) -> errors.Conflict:
    return errors.Conflict(
        f"Could not save a copy of the current database first, so nothing was imported ({exc})."
    )


def _copy_live_file_sync(live: Path) -> str:
    """The undo copy of a live database FILE, through a read-only connection.

    Taken while the swap's connection holds the write lock (see `apply`): in
    WAL a reader proceeds beside a writer, and no other connection can commit
    until the swap does, so the copy is exactly the collection being replaced.
    fsynced into place (`upgrade_guard.copy_into_place`) before the swap
    commits — the swap is durable the moment it does, and a power cut that
    kept it but lost this copy would leave the import without its undo.
    """
    try:
        final = upgrade_guard.copy_into_place(live, _undo_copy_path(), read_only=True)
    except Exception as exc:  # a refusal, re-raised as one
        raise _undo_copy_failed(exc) from exc
    upgrade_guard.prune(final.parent, KEEP_SNAPSHOTS, SNAPSHOT_PREFIX)
    return final.name


async def _copy_on_connection(conn) -> str:
    """The undo copy of a database that is not a file (the test suite's in-memory one).

    Only the swap's own connection can see it, so the copy is made there,
    before its transaction begins; nothing else shares that database to
    write in between.
    """
    final = await asyncio.to_thread(_undo_copy_path)
    partial = final.with_name(final.name + ".partial")
    try:
        await conn.exec_driver_sql("VACUUM INTO ?", (str(partial),))
        await asyncio.to_thread(disk.sync_replace, partial, final)
    except Exception as exc:  # a refusal, re-raised as one
        partial.unlink(missing_ok=True)
        raise _undo_copy_failed(exc) from exc
    await asyncio.to_thread(upgrade_guard.prune, final.parent, KEEP_SNAPSHOTS, SNAPSHOT_PREFIX)
    return final.name


def _restore_photos_sync(staged: _StagedImport) -> int:
    """Write the archive's photos into the upload dir. Returns how many.

    Never deletes and never overwrites: a file already on disk is kept,
    whatever the archive holds under its name. Names are UUIDs, so the same
    name is the same hat's photo — but a re-cut rewrites its cutout under the
    SAME name, so the newer cut on disk wins over the archive's older one.
    That way restoring the `pre-import-*.db` snapshot later brings back a
    collection whose pictures are all still there. The logo is this
    install's: restored only when there is none.
    """
    upload_dir = settings.upload_dir
    room = _room(upload_dir)
    if room is not None and staged.photo_bytes > room:
        raise errors.Conflict(
            f"Not enough free space for the photos: they need {_mb(staged.photo_bytes)} "
            f"and {_mb(room)} can be used."
        )
    keep_logo = branding.find_logo() is not None
    wanted = dict(staged.photos)
    restored = 0
    assert staged.archive is not None
    with tarfile.open(staged.archive, mode="r:gz") as tar:
        for member in tar:
            rel = wanted.get(member.name)
            if rel is None or not member.isfile():
                continue
            if keep_logo and rel.startswith("branding/"):
                continue
            dest = safe_join(upload_dir, *rel.split("/"))
            if dest is None or dest.exists():
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            partial = dest.with_name(dest.name + ".importing")
            try:
                with source, partial.open("wb") as out:
                    shutil.copyfileobj(source, out, _COPY_CHUNK)
                partial.replace(dest)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            restored += 1
    return restored


def _as_number(value: str | None) -> int:
    return int(value) if value and value.isdigit() else 0


def _swap_sync(conn: Connection, keep_account: bool) -> None:
    """Replace the live rows with the attached `incoming` database's. One transaction."""
    replaced = [
        t for t in Base.metadata.sorted_tables
        if not (keep_account and t.name in _ACCOUNT_TABLES)
    ]
    # Read what the live database says before it is gone.
    live_settings = dict(conn.execute(select(AppSetting.key, AppSetting.value)).all())
    live_case_numbers = {
        case_type: conn.execute(
            select(func.coalesce(func.max(Case.sequence_number), 0))
            .where(Case.case_type == case_type.value)
        ).scalar_one()
        for case_type in case_service.RELEASED_SEQUENCE_KEYS
    }

    for t in reversed(replaced):
        conn.execute(delete(t))
    for t in replaced:
        # Column by column, by name: the staged copy went through the same
        # migrations, so it has every column — but an upgraded database adds
        # them at the END, so its column ORDER is not the model's.
        names = [c.name for c in t.columns]
        incoming = table(t.name, *(column(n) for n in names), schema="incoming")
        conn.execute(insert(t).from_select(names, select(*(incoming.c[n] for n in names))))

    _merge_settings(conn, live_settings, live_case_numbers, keep_account)
    _carry_sequences(conn)


def _merge_settings(
    conn: Connection,
    live: dict[str, str | None],
    live_case_numbers: dict,
    keep_account: bool,
) -> None:
    """Apply `setting_policy` over the import's settings, now in place."""
    imported = dict(conn.execute(select(AppSetting.key, AppSetting.value)).all())
    decided: dict[str, str | None] = {}
    for key in set(live) | set(imported):
        policy = setting_policy(key, keep_account=keep_account)
        if policy is SettingPolicy.keep:
            decided[key] = live.get(key)
        elif policy is SettingPolicy.prefer_live and live.get(key):
            decided[key] = live[key]
    # A case number is never issued twice (see `case_service`): the live
    # cases' numbers are released by this import, so they count as given up.
    for case_type, key in case_service.RELEASED_SEQUENCE_KEYS.items():
        highest = max(
            _as_number(live.get(key)), _as_number(imported.get(key)), live_case_numbers[case_type]
        )
        if highest:
            decided[key] = str(highest)

    settings_table = AppSetting.__table__
    for key, value in decided.items():
        if value is None:
            conn.execute(delete(settings_table).where(settings_table.c.key == key))
        else:
            conn.execute(
                sqlite_insert(settings_table)
                .values(key=key, value=value)
                .on_conflict_do_update(index_elements=["key"], set_={"value": value})
            )


def _carry_sequences(conn: Connection) -> None:
    """AUTOINCREMENT high-water marks: the larger of the two databases'.

    The DELETE above leaves the live marks where they were, and the INSERT
    raises them to the largest imported id; the import's own marks — higher
    than its largest surviving id when its newest hats were deleted — are
    folded in here.
    """
    # `sqlite_sequence` exists once a database has an AUTOINCREMENT table; a
    # database that never had one has nothing to carry.
    main_has = conn.execute(text(
        "SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    )).first()
    incoming_has = conn.execute(text(
        "SELECT 1 FROM incoming.sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    )).first()
    if main_has is None or incoming_has is None:
        return
    conn.execute(text(
        "UPDATE main.sqlite_sequence SET seq = MAX(seq, COALESCE("
        "(SELECT i.seq FROM incoming.sqlite_sequence AS i WHERE i.name = sqlite_sequence.name), 0))"
    ))
    conn.execute(text(
        "INSERT INTO main.sqlite_sequence (name, seq) "
        "SELECT i.name, i.seq FROM incoming.sqlite_sequence AS i "
        "WHERE i.name NOT IN (SELECT name FROM main.sqlite_sequence) "
        "AND i.name IN (SELECT name FROM main.sqlite_master WHERE type = 'table')"
    ))


async def _backfill_derivatives(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Thumbnails, then export images, for imported hats that lack them.

    The boot runs the same two sweeps; an import replaces the collection
    without a boot. Usually nothing to do — an archive carries both — but a
    database-only import over photos on disk may need every thumbnail.
    """
    try:
        async with session_factory() as db:
            made = await hat_service.backfill_thumbnails(db)
        async with session_factory() as db:
            made += await hat_service.backfill_export_images(db)
        if made:
            logger.info("Made %d missing thumbnail/export image(s) after an import", made)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — cache warming after an import; never fatal
        logger.warning("Post-import image backfill failed: %s", exc)


async def apply(
    token: str,
    *,
    bind: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    resume: bool = True,
) -> DatabaseImportResult:
    """Replace the live collection with the staged one (see module doc).

    `resume=False` is the command line's: no workers run in that process,
    and the next boot re-queues and backfills anyway.
    """
    global _waiting
    current = _waiting
    if current is None or current.preview.token != token:
        raise errors.NotFound("That import is no longer waiting. Choose the file again.")
    if time.monotonic() > current.expires:
        await discard()
        raise errors.NotFound("That import waited too long and was dropped. Choose the file again.")
    lock = locks.loop_lock("database-import")
    if lock.locked():
        raise errors.Conflict("An import is already running.")

    async with lock:
        await _refuse_if_busy(session_factory)
        async with session_factory() as db:
            keep_account = await auth_service.user_count(db) > 0
        # Photos first, before the undo copy and the swap: they are new files
        # no row points at yet, and a large archive takes a while. The copy
        # comes LAST, right against the swap, so nothing written meanwhile —
        # a wear, an edit — is in neither database.
        restored = (
            await asyncio.to_thread(_restore_photos_sync, current)
            if current.archive is not None else 0
        )
        live_file = upgrade_guard.sqlite_file(bind.url)
        # Under the shelf lock, so no placement decision reads the old cases
        # and commits into the new ones; checked once more for work that
        # started while the photos were being written.
        async with capacity.placement_lock():
            await _refuse_if_busy(session_factory)
            async with bind.connect() as conn:
                await conn.exec_driver_sql(
                    "ATTACH DATABASE ? AS incoming", (str(current.database),)
                )
                try:
                    if live_file is None:
                        snapshot = await _copy_on_connection(conn)
                    # The write lock, taken BEFORE the copy: from here to the
                    # commit no other connection can commit a write (they wait
                    # out `busy_timeout`), so the copy below is exactly the
                    # collection the swap replaces. Explicit, because the
                    # driver otherwise begins a deferred transaction only at
                    # the first DELETE — after the copy.
                    await conn.exec_driver_sql("BEGIN IMMEDIATE")
                    if live_file is not None:
                        snapshot = await asyncio.to_thread(_copy_live_file_sync, live_file)
                    await conn.run_sync(_swap_sync, keep_account)
                    await conn.commit()
                except BaseException:
                    await conn.rollback()
                    raise
                finally:
                    try:
                        await conn.exec_driver_sql("DETACH DATABASE incoming")
                    except Exception:  # noqa: BLE001 — a connection left holding the attachment is discarded instead
                        logger.warning("Could not detach the imported database; discarding the connection")
                        await conn.invalidate()
        if _waiting is current:
            _waiting = None
        await asyncio.to_thread(backup_service.close_spool_sync, current.spool)

    preview = current.preview
    logger.warning(
        "Imported %s: %d hats replaced %d; the previous database is %s",
        preview.source, preview.hats, preview.current_hats, snapshot,
    )
    async with session_factory() as db:
        await activity_service.log_and_commit(
            db,
            kind="database.imported",
            entity_type="system",
            entity_id=None,
            summary=(
                f"Imported {preview.source}: {_plural(preview.hats, 'hat')} replaced "
                f"{preview.current_hats}. The previous database is saved as {snapshot}."
            ),
            details={
                "source": preview.source,
                "from_server": preview.from_server,
                "version": preview.version,
                "hats": preview.hats,
                "replaced_hats": preview.current_hats,
                "photos_restored": restored,
                "snapshot": snapshot,
                "kept_account": keep_account,
            },
        )
    if resume:
        await analysis_queue.requeue_stranded()
        await import_service.requeue_stranded()
        task = asyncio.create_task(_backfill_derivatives(session_factory))
        _background.add(task)
        task.add_done_callback(_background.discard)
    return DatabaseImportResult(
        source=preview.source,
        hats=preview.hats,
        photos_restored=restored,
        snapshot=snapshot,
        keeps_account=keep_account,
    )

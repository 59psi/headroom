"""Importing a database: a backup's collection in place of this one.

Every test makes its "backup" the way a real one is made — `VACUUM INTO` from
the live database, the same call the scheduled archives and the upgrade
snapshots use — then changes the live collection and imports the file, so
"the old collection is back" is checked against a real earlier state rather
than a hand-built fixture.
"""

from __future__ import annotations

import io
import sqlite3
import tarfile
from pathlib import Path

import pytest
from sqlalchemy import func, select

from headroom import limits
from headroom.config import settings
from headroom.models import ActivityLog, AppSetting, Case, Hat, ShareLink, User
from headroom.routes.admin import database as database_routes
from headroom.services import (
    analysis_queue,
    backup_service,
    database_import,
    guest_view_service,
    settings_service,
    upgrade_guard,
)
from tests import conftest

pytestmark = pytest.mark.anyio

_IMPORT = "/api/admin/database/import"


@pytest.fixture(autouse=True)
async def _clean_slate():
    """No staged import or post-import task leaks between tests."""
    yield
    for task in list(database_import._background):
        await task
    await database_import.discard()


async def _hat(client, model, **extra) -> int:
    body = {"condition": "new", "size": "classic", "style": "odysea", "model_name": model, **extra}
    resp = await client.post("/api/hats", json=body)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _snapshot_to(path: Path) -> Path:
    """The live database as a one-file backup, exactly as the app writes one."""
    async with conftest.test_engine.connect() as conn:
        await conn.exec_driver_sql("VACUUM INTO ?", (str(path),))
    return path


async def _models() -> list[str]:
    async with conftest.test_session_factory() as db:
        rows = (await db.execute(select(Hat.model_name).order_by(Hat.id))).scalars().all()
    return list(rows)


async def _upload(client, path: Path, name: str | None = None):
    return await client.post(
        _IMPORT,
        params={"filename": name or path.name},
        content=path.read_bytes(),
        headers={"content-type": "application/octet-stream"},
    )


async def _import(client, path: Path) -> dict:
    staged = await _upload(client, path)
    assert staged.status_code == 200, staged.text
    applied = await client.post(f"{_IMPORT}/{staged.json()['token']}/apply")
    assert applied.status_code == 200, applied.text
    return applied.json()


def _archive(dest: Path, db: Path | None, photos: dict[str, bytes] | None = None,
             extra: dict[str, bytes] | None = None) -> Path:
    with tarfile.open(dest, "w:gz") as tar:
        if db is not None:
            tar.add(db, arcname="data/headroom.db")
        for name, data in {**{f"data/uploads/{k}": v for k, v in (photos or {}).items()},
                           **(extra or {})}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return dest


# ---- the round trip -------------------------------------------------------- #


async def test_an_imported_backup_replaces_the_collection(client, tmp_path):
    await _hat(client, "Odysea Hydro")
    await _hat(client, "Trenches Hydro")
    backup = await _snapshot_to(tmp_path / "backup.db")
    await _hat(client, "Added After The Backup")

    staged = await _upload(client, backup)
    assert staged.status_code == 200, staged.text
    preview = staged.json()
    assert (preview["hats"], preview["current_hats"]) == (2, 3)
    assert preview["kind"] == "database" and preview["keeps_account"] is True
    # Staging changes nothing live.
    assert await _models() == ["Odysea Hydro", "Trenches Hydro", "Added After The Backup"]

    applied = await client.post(f"{_IMPORT}/{preview['token']}/apply")
    assert applied.status_code == 200, applied.text
    assert await _models() == ["Odysea Hydro", "Trenches Hydro"]


async def test_the_replaced_database_is_saved_first_and_is_itself_a_restore_point(client, tmp_path):
    await _hat(client, "In The Backup")
    backup = await _snapshot_to(tmp_path / "backup.db")
    await _hat(client, "Only Live")

    result = await _import(client, backup)

    saved = backup_service._backup_dir() / result["snapshot"]
    assert saved.name.startswith(database_import.SNAPSHOT_PREFIX)
    conn = sqlite3.connect(saved)
    try:
        models = [r[0] for r in conn.execute("SELECT model_name FROM hats ORDER BY id")]
    finally:
        conn.close()
    assert models == ["In The Backup", "Only Live"], "the undo copy is not the replaced collection"

    points = (await client.get("/api/admin/database/restore-points")).json()
    assert {"name": saved.name, "kind": "snapshot"}.items() <= next(
        p for p in points if p["name"] == saved.name
    ).items()

    # ...and importing it is the undo.
    staged = await client.post(f"{_IMPORT}/restore-point", json={"name": saved.name})
    assert staged.status_code == 200, staged.text
    undone = await client.post(f"{_IMPORT}/{staged.json()['token']}/apply")
    assert undone.status_code == 200, undone.text
    assert await _models() == ["In The Backup", "Only Live"]


async def test_a_swap_that_fails_half_way_changes_nothing(client, tmp_path, monkeypatch):
    """Every table is emptied and refilled in ONE transaction. Fail it after
    the rows have moved — in the last step — and the live collection must be
    exactly what it was, not empty and not half-imported."""
    await _hat(client, "In The Backup")
    backup = await _snapshot_to(tmp_path / "backup.db")
    await _hat(client, "Live Only")
    staged = (await _upload(client, backup)).json()

    def explode(conn):
        raise RuntimeError("disk pulled out mid-swap")

    monkeypatch.setattr(database_import, "_carry_sequences", explode)
    with pytest.raises(RuntimeError):
        await database_import.apply(
            staged["token"],
            bind=conftest.test_engine,
            session_factory=conftest.test_session_factory,
        )

    assert await _models() == ["In The Backup", "Live Only"]
    # ...and the connection is usable afterwards, the import detached.
    assert await _hat(client, "After The Failure")


async def test_on_a_file_database_every_connection_sees_the_import(file_client, file_engine, tmp_path):
    """The production shape: a WAL file database and a POOL of connections,
    so the swap runs on one connection and the next request reads on
    another. A file copied under an open connection is what this design
    avoids; the rows must simply be there for every reader after the commit."""
    engine, _ = file_engine

    async def models():
        return [h["model_name"] for h in (await file_client.get("/api/hats")).json()]

    await _hat(file_client, "In The Backup")
    backup = tmp_path / "file-backup.db"
    async with engine.connect() as conn:
        await conn.exec_driver_sql("VACUUM INTO ?", (str(backup),))
    await _hat(file_client, "Live Only")
    assert set(await models()) == {"In The Backup", "Live Only"}

    await _import(file_client, backup)

    assert await models() == ["In The Backup"]
    assert (await file_client.get("/api/auth/me")).status_code == 200


async def test_on_a_file_database_a_failed_swap_changes_nothing(
    file_client, file_engine, tmp_path, monkeypatch
):
    engine, factory = file_engine
    await _hat(file_client, "In The Backup")
    backup = tmp_path / "file-backup.db"
    async with engine.connect() as conn:
        await conn.exec_driver_sql("VACUUM INTO ?", (str(backup),))
    await _hat(file_client, "Live Only")
    staged = (await _upload(file_client, backup)).json()

    def explode(conn):
        raise RuntimeError("disk pulled out mid-swap")

    monkeypatch.setattr(database_import, "_carry_sequences", explode)
    with pytest.raises(RuntimeError):
        await database_import.apply(staged["token"], bind=engine, session_factory=factory)

    names = {h["model_name"] for h in (await file_client.get("/api/hats")).json()}
    assert names == {"In The Backup", "Live Only"}


async def test_the_import_is_recorded_in_the_imported_history(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    result = await _import(client, backup)
    async with conftest.test_session_factory() as db:
        row = (await db.execute(
            select(ActivityLog).where(ActivityLog.kind == "database.imported")
        )).scalar_one()
    assert result["snapshot"] in row.summary


# ---- what an import keeps --------------------------------------------------- #


async def test_the_account_and_sign_in_survive_an_import(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.execute("UPDATE users SET username = 'someone-else', api_token = 'hr_other'")
    conn.execute("DELETE FROM auth_sessions")
    conn.commit()
    conn.close()

    await _import(client, backup)

    # The same cookie still works: the session row was kept, not imported.
    assert (await client.get("/api/auth/me")).status_code == 200
    async with conftest.test_session_factory() as db:
        names = (await db.execute(select(User.username))).scalars().all()
    assert names == ["testowner"]


async def test_share_links_are_this_installs_not_the_backups(client, tmp_path, db_session):
    db_session.add(ShareLink(token="revoked-since-the-backup", label="old"))
    await db_session.commit()
    backup = await _snapshot_to(tmp_path / "backup.db")
    await db_session.execute(ShareLink.__table__.delete())
    db_session.add(ShareLink(token="made-after-the-backup", label="new"))
    await db_session.commit()

    await _import(client, backup)

    async with conftest.test_session_factory() as db:
        tokens = (await db.execute(select(ShareLink.token))).scalars().all()
    assert tokens == ["made-after-the-backup"], "an import brought a deleted share link back"


async def test_settings_this_install_has_win_and_the_import_fills_the_rest(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.executemany("INSERT INTO app_settings (key, value) VALUES (?, ?)", [
        ("anthropic_api_key", "sk-from-the-backup"),
        ("tag_base_url", "https://from-the-backup.example"),
        (guest_view_service.GUEST_VIEW_KEY, "true"),
        ("ca_root_sha256", "another-servers-root"),
        ("case_seq_released_archive", "2"),
    ])
    conn.commit()
    conn.close()
    async with conftest.test_session_factory() as db:
        db.add(AppSetting(key="anthropic_api_key", value="sk-live"))
        await db.commit()

    await _import(client, backup)

    async with conftest.test_session_factory() as db:
        got = dict((await db.execute(select(AppSetting.key, AppSetting.value))).all())
    assert got["anthropic_api_key"] == "sk-live", "the live key was replaced by the backup's"
    assert got["tag_base_url"] == "https://from-the-backup.example", "an unset setting was not filled in"
    assert guest_view_service.GUEST_VIEW_KEY not in got, "guest browsing was switched on by an import"
    assert "ca_root_sha256" not in got, "another server's CA fingerprint was adopted"
    assert got[upgrade_guard.LAST_BOOTED_KEY] == upgrade_guard.running_version()


async def test_a_key_set_by_environment_is_not_outranked_by_an_imported_one(
    client, tmp_path, monkeypatch
):
    """`get_key` reads the database first and the environment only when there
    is no row — so a backup's row for a key this server sets by environment
    would silently replace it. An installed key stays exactly as it is."""
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('anthropic_api_key', 'sk-old-from-backup')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-from-environment")

    await _import(client, backup)

    async with conftest.test_session_factory() as db:
        key, source = await settings_service.get_key(db, settings_service.ANTHROPIC_KEY)
    assert (key, source) == ("sk-from-environment", "environment")


async def test_an_off_site_destination_removed_since_the_backup_stays_removed(client, tmp_path):
    """The archive holds the keys; a destination the owner removed must not
    come back with an old backup and start receiving them again."""
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.executemany("INSERT INTO app_settings (key, value) VALUES (?, ?)", [
        (backup_service.UPLOAD_PROVIDER_KEY, "rclone"),
        (backup_service.UPLOAD_DESTINATION_KEY, "old-remote:backups"),
    ])
    conn.commit()
    conn.close()

    await _import(client, backup)

    async with conftest.test_session_factory() as db:
        assert await settings_service.get_setting(db, backup_service.UPLOAD_DESTINATION_KEY) is None


async def test_every_one_time_repair_ran_on_the_import(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.execute("DELETE FROM app_settings WHERE value = 'done'")
    conn.commit()
    conn.close()

    await _import(client, backup)

    from headroom.services import database_upgrade

    async with conftest.test_session_factory() as db:
        done = set((await db.execute(
            select(AppSetting.key).where(AppSetting.value == "done")
        )).scalars().all())
    assert {flag for flag, _, _ in database_upgrade.ONE_TIME_REPAIRS} <= done


async def test_setting_policy_defaults_to_keeping_what_works_here():
    assert database_import.setting_policy("some_future_setting", keep_account=True) == "prefer_live"
    assert database_import.setting_policy(upgrade_guard.LAST_BOOTED_KEY, keep_account=True) == "import"
    assert database_import.setting_policy(guest_view_service.GUEST_VIEW_KEY, keep_account=True) == "keep"
    # A database with no account here (the command line on a fresh install)
    # takes the import's access along with its account.
    assert database_import.setting_policy(guest_view_service.GUEST_VIEW_KEY, keep_account=False) == "import"


# ---- numbers on stickers never go backwards --------------------------------- #


async def test_a_hat_id_is_never_issued_twice_across_an_import(client, tmp_path):
    first = await _hat(client, "In The Backup")
    backup = await _snapshot_to(tmp_path / "backup.db")
    later = [await _hat(client, f"After {i}") for i in range(3)]

    await _import(client, backup)
    fresh = await _hat(client, "Made After The Import")

    assert fresh > max(later), (
        f"hat #{fresh} reuses an id a sticker for a hat made after the backup still carries"
    )
    assert fresh != first


async def test_the_imports_own_high_water_mark_is_kept_too(client, tmp_path):
    """The other direction: a backup whose newest hats were deleted has a
    sequence above its largest surviving id. The live mark never drops (a
    DELETE leaves it), so only carrying the import's own keeps those ids
    retired."""
    await _hat(client, "In The Backup")
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.execute("UPDATE sqlite_sequence SET seq = 50 WHERE name = 'hats'")
    conn.commit()
    conn.close()

    await _import(client, backup)

    assert await _hat(client, "Next") == 51


async def test_a_case_number_is_never_issued_twice_across_an_import(client, tmp_path):
    await client.post("/api/cases", json={"case_type": "archive"})
    backup = await _snapshot_to(tmp_path / "backup.db")
    for _ in range(3):
        await client.post("/api/cases", json={"case_type": "archive"})  # up to A-004

    await _import(client, backup)
    made = (await client.post("/api/cases", json={"case_type": "archive"})).json()

    assert made["sequence_number"] == 5, f"got {made['display_id']}: a printed case tag now points elsewhere"


# ---- photos ------------------------------------------------------------------ #


async def test_an_archive_restores_its_photos_and_reports_them(client, tmp_path):
    pictured = await _hat(client, "Pictured")
    pictureless = await _hat(client, "Pictureless")
    async with conftest.test_session_factory() as db:
        (await db.get(Hat, pictured)).photo_path = "hats/abc.png"
        (await db.get(Hat, pictureless)).photo_path = "hats/gone.png"
        await db.commit()
    backup = await _snapshot_to(tmp_path / "backup.db")
    archive = _archive(tmp_path / "headroom-backup.tar.gz", backup, {
        "hats/abc.png": b"PNGDATA",
        "hats/thumbs/abc.webp": b"THUMB",
    })

    staged = (await _upload(client, archive)).json()
    assert (staged["kind"], staged["photos_included"], staged["photos_missing"]) == ("archive", 1, 1)
    await client.post(f"{_IMPORT}/{staged['token']}/apply")

    assert (settings.upload_dir / "hats" / "abc.png").read_bytes() == b"PNGDATA"
    assert (settings.upload_dir / "hats" / "thumbs" / "abc.webp").read_bytes() == b"THUMB"


async def test_a_photo_already_on_disk_is_never_overwritten(client, tmp_path):
    """A re-cut rewrites its cutout under the SAME name. An archive from
    before it holds the older cut; writing that over the newer one would
    lose a picture the undo copy still points at."""
    hat_id = await _hat(client, "Re-cut Since")
    async with conftest.test_session_factory() as db:
        (await db.get(Hat, hat_id)).photo_path = "hats/same.png"
        await db.commit()
    backup = await _snapshot_to(tmp_path / "backup.db")
    archive = _archive(tmp_path / "older.tar.gz", backup, {"hats/same.png": b"OLDER-CUT"})
    (settings.upload_dir / "hats" / "same.png").write_bytes(b"the newer cut")

    await _import(client, archive)

    assert (settings.upload_dir / "hats" / "same.png").read_bytes() == b"the newer cut"


async def test_an_archive_never_writes_outside_the_photo_folders(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    archive = _archive(tmp_path / "evil.tar.gz", backup, extra={
        "data/uploads/../../escaped.txt": b"x",
        # Inside a photo folder by its first parts, outside by its last.
        "data/uploads/hats/../../escaped-too.txt": b"x",
        "data/uploads/elsewhere/file.txt": b"x",
        "/data/uploads/hats/absolute.png": b"x",
    })
    await _import(client, archive)
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "escaped-too.txt").exists()
    assert not (settings.upload_dir / "elsewhere").exists()
    assert not (settings.upload_dir / "hats" / "absolute.png").exists()


async def test_a_finder_appledouble_file_is_not_taken_for_the_database(client, tmp_path):
    await _hat(client, "Real")
    backup = await _snapshot_to(tmp_path / "backup.db")
    # Not named headroom.db, which would be chosen by name whatever sat
    # beside it: with the junk counted, this archive holds "two databases".
    archive = _archive(tmp_path / "repacked.tar.gz", None, extra={
        "data/._collection.db": b"\x00\x05\x16\x07 AppleDouble junk",
        "data/collection.db": backup.read_bytes(),
    })
    staged = await _upload(client, archive)
    assert staged.status_code == 200, staged.text
    assert staged.json()["hats"] == 1


# ---- an older database comes up to date --------------------------------------- #


async def test_an_older_database_is_migrated_on_the_way_in(client, tmp_path):
    await _hat(client, "From 2.80")
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.execute("ALTER TABLE hats DROP COLUMN construction_source")
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, '2.80.0')",
        (upgrade_guard.LAST_BOOTED_KEY,),
    )
    conn.commit()
    conn.close()

    staged = await _upload(client, backup)
    assert staged.status_code == 200, staged.text
    assert staged.json()["version"] == "2.80.0"
    await client.post(f"{_IMPORT}/{staged.json()['token']}/apply")
    assert await _models() == ["From 2.80"]


# ---- refusals ------------------------------------------------------------------ #


async def test_a_file_that_is_neither_refuses(client, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("hello")
    resp = await _upload(client, junk)
    assert resp.status_code == 400
    assert "not a Headroom backup" in resp.json()["detail"]


async def test_a_sqlite_file_that_is_not_headroom_refuses(client, tmp_path):
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE recipes (id INTEGER)")
    conn.commit()
    conn.close()
    resp = await _upload(client, other)
    assert resp.status_code == 400
    assert "not a Headroom one" in resp.json()["detail"]


async def test_an_archive_without_a_database_refuses(client, tmp_path):
    archive = _archive(tmp_path / "photos-only.tar.gz", None, {"hats/a.png": b"x"})
    resp = await _upload(client, archive)
    assert resp.status_code == 400
    assert "no database" in resp.json()["detail"]


async def test_a_truncated_archive_refuses(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    archive = _archive(tmp_path / "full.tar.gz", backup, {"hats/a.png": b"x" * 50_000})
    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    resp = await _upload(client, cut)
    assert resp.status_code == 400
    assert "complete" in resp.json()["detail"]


async def test_an_archive_database_bigger_than_the_room_left_is_not_extracted(
    client, tmp_path, monkeypatch
):
    """The database inside an archive is bounded like an upload: its declared
    size is checked before a byte is written, so a tiny gzip that inflates to
    a huge "database" cannot fill the data volume during staging."""
    backup = await _snapshot_to(tmp_path / "backup.db")
    archive = _archive(tmp_path / "big.tar.gz", backup)
    # Room for the upload itself (a few KB), not for what it unpacks to.
    monkeypatch.setattr(database_import, "MAX_UPLOAD_BYTES", archive.stat().st_size + 1024)
    assert backup.stat().st_size > archive.stat().st_size + 1024

    resp = await _upload(client, archive)

    assert resp.status_code == 400
    assert "room for" in resp.json()["detail"]


async def test_a_database_from_a_newer_headroom_refuses(client, tmp_path, monkeypatch):
    backup = await _snapshot_to(tmp_path / "backup.db")
    conn = sqlite3.connect(backup)
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, '99.0.0')",
        (upgrade_guard.LAST_BOOTED_KEY,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(upgrade_guard, "running_version", lambda: "2.85.0")
    resp = await _upload(client, backup)
    assert resp.status_code == 400
    assert "Upgrade this server first" in resp.json()["detail"]


async def test_nothing_is_replaced_while_a_photo_is_being_analyzed(client, tmp_path, monkeypatch):
    backup = await _snapshot_to(tmp_path / "backup.db")
    hat_id = await _hat(client, "Busy")
    async with conftest.test_session_factory() as db:
        (await db.get(Hat, hat_id)).analysis_status = analysis_queue.PENDING
        await db.commit()
    monkeypatch.setattr(analysis_queue, "worker_alive", lambda: True)

    staged = (await _upload(client, backup)).json()
    resp = await client.post(f"{_IMPORT}/{staged['token']}/apply")

    assert resp.status_code == 409
    assert "being analyzed" in resp.json()["detail"]
    assert await _models() == ["Busy"]
    assert not list(backup_service._backup_dir().glob(f"{database_import.SNAPSHOT_PREFIX}*"))


async def test_nothing_is_replaced_while_a_request_runs_the_pipeline_itself(client, tmp_path):
    """With no worker, a request runs the analysis inline — writing to a hat
    by id like the worker does, so the import waits for it the same way."""
    backup = await _snapshot_to(tmp_path / "backup.db")
    staged = (await _upload(client, backup)).json()

    async with analysis_queue.running_inline():
        resp = await client.post(f"{_IMPORT}/{staged['token']}/apply")

    assert resp.status_code == 409
    assert "being analyzed" in resp.json()["detail"]


async def test_the_undo_copy_is_made_durable_before_the_swap(client, tmp_path, monkeypatch):
    """fsynced and renamed into place before the swap commits: a power cut
    that kept the new collection must not have lost the copy of the old."""
    from headroom.utils import disk

    order: list[str] = []
    real = disk.sync_replace

    def recording(partial, final):
        order.append(f"sync {final.name}")
        real(partial, final)

    real_swap = database_import._swap_sync
    monkeypatch.setattr(disk, "sync_replace", recording)
    monkeypatch.setattr(
        database_import, "_swap_sync",
        lambda conn, keep: (order.append("swap"), real_swap(conn, keep))[1],
    )
    backup = await _snapshot_to(tmp_path / "backup.db")

    result = await _import(client, backup)

    assert order == [f"sync {result['snapshot']}", "swap"]


async def test_a_write_during_the_photo_restore_is_in_the_undo_copy(file_client, file_engine, tmp_path, monkeypatch):
    """The copy is taken under the write lock, right against the swap — not
    before the photos, when anything written while a big archive unpacked was
    lost from both databases. On a file database, as in production."""
    engine, factory = file_engine
    await _hat(file_client, "In The Backup")
    backup = tmp_path / "file-backup.db"
    async with engine.connect() as conn:
        await conn.exec_driver_sql("VACUUM INTO ?", (str(backup),))
    archive = _archive(tmp_path / "with-photo.tar.gz", backup, {"hats/p.png": b"x"})
    live = Path(engine.url.database)
    real_restore = database_import._restore_photos_sync

    def restore_while_someone_writes(staged):
        conn = sqlite3.connect(live)
        conn.execute("INSERT INTO rooms (name, is_default) VALUES ('Written Meanwhile', 0)")
        conn.commit()
        conn.close()
        return real_restore(staged)

    monkeypatch.setattr(database_import, "_restore_photos_sync", restore_while_someone_writes)

    result = await _import(file_client, archive)

    copy = sqlite3.connect(backup_service._backup_dir() / result["snapshot"])
    try:
        rooms = {r[0] for r in copy.execute("SELECT name FROM rooms")}
    finally:
        copy.close()
    assert "Written Meanwhile" in rooms, "a write made during the import is in neither database"


async def test_no_other_writer_can_commit_between_the_copy_and_the_swap(
    file_client, file_engine, tmp_path, monkeypatch
):
    """The write lock is taken BEFORE the undo copy, so between the copy and
    the swap's commit another connection's write waits (and here, with no
    patience, fails) instead of landing in neither database."""
    engine, _ = file_engine
    await _hat(file_client, "In The Backup")
    backup = tmp_path / "file-backup.db"
    async with engine.connect() as conn:
        await conn.exec_driver_sql("VACUUM INTO ?", (str(backup),))
    live = Path(engine.url.database)
    real_snapshot = database_import._snapshot_file_sync
    outcome = {}

    def snapshot_then_try_a_write(path):
        name = real_snapshot(path)
        conn = sqlite3.connect(live, timeout=0.2)
        try:
            conn.execute("INSERT INTO rooms (name, is_default) VALUES ('Snuck In', 0)")
            conn.commit()
            outcome["write"] = "landed"
        except sqlite3.OperationalError as exc:
            outcome["write"] = str(exc)
        finally:
            conn.close()
        return name

    monkeypatch.setattr(database_import, "_snapshot_file_sync", snapshot_then_try_a_write)

    await _import(file_client, backup)

    assert outcome["write"] == "database is locked", "a write committed between the copy and the swap"


async def test_a_stale_or_discarded_token_applies_nothing(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    await _hat(client, "Live")
    staged = (await _upload(client, backup)).json()

    assert (await client.post(f"{_IMPORT}/not-the-token/apply")).status_code == 404
    assert (await client.delete(f"{_IMPORT}/{staged['token']}")).status_code == 204
    assert (await client.post(f"{_IMPORT}/{staged['token']}/apply")).status_code == 404
    assert await _models() == ["Live"]


async def test_staging_a_second_file_drops_the_first(client, tmp_path):
    backup = await _snapshot_to(tmp_path / "backup.db")
    first = (await _upload(client, backup)).json()
    first_spool = database_import._staged.spool
    second = (await _upload(client, backup)).json()

    assert not first_spool.exists(), "an abandoned preview left its copy on the data volume"
    assert (await client.post(f"{_IMPORT}/{first['token']}/apply")).status_code == 404
    assert (await client.get(_IMPORT)).json()["token"] == second["token"]


async def test_a_restore_point_is_looked_up_never_joined_onto_a_path(client, tmp_path):
    resp = await client.post(f"{_IMPORT}/restore-point", json={"name": "../headroom.db"})
    assert resp.status_code == 404


async def test_restore_points_list_archives_and_snapshots_only(client):
    root = backup_service._backup_dir()
    for name in (
        "headroom-backup-2026-10-17T06-42-01Z.tar.gz",
        "pre-upgrade-2.84.0-to-2.84.1-2026-10-17T23-31-04Z.db",
        "headroom-backup-2026-10-18T06-42-01Z.tar.gz.partial",
        ".last-fingerprint",
        "notes.txt",
    ):
        (root / name).write_bytes(b"x")
    names = {p["name"]: p["kind"] for p in (await client.get("/api/admin/database/restore-points")).json()}
    assert names == {
        "headroom-backup-2026-10-17T06-42-01Z.tar.gz": "archive",
        "pre-upgrade-2.84.0-to-2.84.1-2026-10-17T23-31-04Z.db": "snapshot",
    }


# ---- the upload path ----------------------------------------------------------- #


async def test_the_upload_streams_past_the_ordinary_body_cap(client, tmp_path, monkeypatch):
    """The ordinary cap is 2 MB; an archive is hundreds. The import endpoint
    declares its own, and the body goes to the data volume, not /tmp."""
    monkeypatch.setattr(limits, "DEFAULT_MAX_BODY_BYTES", 1024)
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1024")
    backup = await _snapshot_to(tmp_path / "backup.db")
    assert backup.stat().st_size > 1024
    resp = await _upload(client, backup)
    assert resp.status_code == 200, resp.text
    assert database_import._staged.spool.is_relative_to(backup_service._backup_dir())


async def test_the_import_endpoint_declares_its_own_ceiling():
    assert limits.endpoint_cap(database_routes.stage_upload, 2048) == database_import.MAX_UPLOAD_BYTES
    # ...and a raw body sent to any other route still gets the ordinary cap.
    assert limits.endpoint_cap(database_routes.stage_restore_point, 2048) == 2048


async def test_an_upload_larger_than_the_room_left_refuses(client, tmp_path, monkeypatch):
    monkeypatch.setattr(database_import, "MAX_UPLOAD_BYTES", 4096)
    backup = await _snapshot_to(tmp_path / "backup.db")
    resp = await _upload(client, backup)
    assert resp.status_code == 400
    assert "room for" in resp.json()["detail"]
    assert not list((backup_service._backup_dir() / ".spool").iterdir()), "a refused upload left a file"


async def test_an_import_needs_a_login(anon_client, tmp_path):
    resp = await anon_client.post(
        _IMPORT, content=b"x", headers={"content-type": "application/octet-stream"}
    )
    assert resp.status_code == 401


async def test_case_count_survives_in_the_preview(client, tmp_path):
    await client.post("/api/cases", json={"case_type": "archive"})
    backup = await _snapshot_to(tmp_path / "backup.db")
    preview = (await _upload(client, backup)).json()
    async with conftest.test_session_factory() as db:
        live_cases = (await db.execute(select(func.count(Case.id)))).scalar_one()
    assert preview["cases"] == live_cases == 1

"""Configuring the off-box backup copy from the UI, without opening an RCE.

The upload hook runs an argv, unattended, as the app user, after every backup.
Making that settable from a browser is the kind of feature that turns a stolen
session into command execution — so the browser does NOT send a command. It
sends a provider name and a destination, and the argv is assembled from a
template this app owns.

These tests exist to keep that property true. The interesting cases are not
"does the happy path work" but "what does the validator refuse", because the
day someone relaxes it to accept a convenient extra flag is the day the
boundary is gone.
"""

from __future__ import annotations

import pytest

from headroom.services import backup_service

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _fresh_health():
    backup_service._health = backup_service.BackupHealth()
    yield
    backup_service._health = backup_service.BackupHealth()


# ---- the validator ---------------------------------------------------- #


async def test_a_normal_remote_path_is_accepted():
    assert backup_service.validate_destination("box:Headroom") == "box:Headroom"
    assert backup_service.validate_destination(" b2:hats/backups ") == "b2:hats/backups"


@pytest.mark.parametrize("bad", [
    "--config=/etc/rclone.conf",   # flag injection wearing an argument's clothes
    "-v",
    "box:Headroom; rm -rf /",      # shell metacharacters
    "box:Headroom && curl evil",
    "box:$(whoami)",
    "box:`id`",
    "box:Head|tee",
    "",
    "   ",
])
async def test_the_validator_refuses_anything_that_is_not_a_remote_path(bad):
    with pytest.raises(ValueError):
        backup_service.validate_destination(bad)


async def test_a_leading_dash_is_called_out_as_a_flag():
    """The error should teach, because this is the one a person might try."""
    with pytest.raises(ValueError, match="flag"):
        backup_service.validate_destination("--config=/etc/x")


# ---- argv assembly ---------------------------------------------------- #


async def test_the_destination_lands_in_exactly_one_argv_slot(client, db_session):
    """The whole safety argument in one assertion.

    No arrangement of user input may change the binary, add an argument, or
    reach a shell — because the template supplies every other element.
    """
    from pathlib import Path

    from headroom.services import settings_service

    await settings_service.set_setting(db_session, backup_service.UPLOAD_PROVIDER_KEY, "rclone")
    await settings_service.set_setting(
        db_session, backup_service.UPLOAD_DESTINATION_KEY, "box:Headroom"
    )
    await db_session.commit()

    argv = await backup_service.resolve_upload_argv(db_session, Path("/data/backups/x.tar.gz"))

    assert argv == ["rclone", "copy", "/data/backups/x.tar.gz", "box:Headroom"]
    assert argv.count("box:Headroom") == 1


async def test_a_stored_destination_that_no_longer_validates_is_refused(
    client, db_session, caplog
):
    """Belt and braces: the validator runs again at USE time.

    A value can reach the database by a route the endpoint did not police — a
    restored backup, a manual edit, a future migration — and the answer to
    "this looks wrong" must be "run nothing", never "run it anyway".
    """
    from pathlib import Path

    from headroom.services import settings_service

    caplog.set_level("ERROR")
    await settings_service.set_setting(db_session, backup_service.UPLOAD_PROVIDER_KEY, "rclone")
    await settings_service.set_setting(
        db_session, backup_service.UPLOAD_DESTINATION_KEY, "--config=/etc/x"
    )
    await db_session.commit()

    argv = await backup_service.resolve_upload_argv(db_session, Path("/tmp/x.tar.gz"))

    assert argv is None
    assert any("invalid" in r.getMessage().lower() for r in caplog.records)


async def test_the_environment_wins_over_the_stored_setting(
    client, db_session, monkeypatch
):
    """Opposite precedence to the API keys, and deliberately so.

    `HEADROOM_BACKUP_UPLOAD_CMD` is a raw command settable only with host
    access. Letting a browser override a host-level decision about what runs
    on every backup would erase exactly the boundary that makes the raw form
    acceptable in the first place.
    """
    from pathlib import Path

    from headroom.services import settings_service

    monkeypatch.setenv("HEADROOM_BACKUP_UPLOAD_CMD", "/usr/bin/true {path}")
    await settings_service.set_setting(db_session, backup_service.UPLOAD_PROVIDER_KEY, "rclone")
    await settings_service.set_setting(
        db_session, backup_service.UPLOAD_DESTINATION_KEY, "box:Headroom"
    )
    await db_session.commit()

    argv = await backup_service.resolve_upload_argv(db_session, Path("/tmp/x.tar.gz"))

    assert argv[0] == "/usr/bin/true"


async def test_no_upload_configured_resolves_to_nothing(client, db_session):
    from pathlib import Path

    assert await backup_service.resolve_upload_argv(db_session, Path("/tmp/x")) is None


# ---- the endpoints ---------------------------------------------------- #


async def test_the_status_endpoint_reports_unconfigured_on_a_fresh_install(client):
    body = (await client.get("/api/admin/backups/upload")).json()

    assert body["configured"] is False
    assert body["available_providers"] == ["rclone"]


async def test_setting_a_destination_round_trips(client):
    resp = await client.put(
        "/api/admin/backups/upload",
        json={"provider": "rclone", "destination": "box:Headroom"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["destination"] == "box:Headroom"
    assert body["from_environment"] is False


async def test_the_endpoint_refuses_an_injected_flag(client):
    resp = await client.put(
        "/api/admin/backups/upload",
        json={"provider": "rclone", "destination": "--config=/etc/rclone.conf"},
    )

    assert resp.status_code == 400
    assert (await client.get("/api/admin/backups/upload")).json()["configured"] is False


async def test_the_endpoint_refuses_an_unknown_provider(client):
    """There is no free-text command field, so this is the only lever on argv[0]."""
    resp = await client.put(
        "/api/admin/backups/upload",
        json={"provider": "bash", "destination": "box:Headroom"},
    )

    assert resp.status_code == 400


async def test_clearing_turns_it_off(client):
    await client.put(
        "/api/admin/backups/upload",
        json={"provider": "rclone", "destination": "box:Headroom"},
    )

    await client.delete("/api/admin/backups/upload")

    assert (await client.get("/api/admin/backups/upload")).json()["configured"] is False


async def test_configuring_it_is_audited(client):
    """It changes what executes on this box. That belongs in the log."""
    await client.put(
        "/api/admin/backups/upload",
        json={"provider": "rclone", "destination": "box:Headroom"},
    )

    rows = (await client.get("/api/admin/activity-log?limit=20")).json()

    assert any(r["kind"] == "backup.upload_configured" for r in rows)


async def test_the_upload_endpoints_need_auth(anon_client):
    assert (await anon_client.get("/api/admin/backups/upload")).status_code == 401
    assert (await anon_client.put(
        "/api/admin/backups/upload",
        json={"provider": "rclone", "destination": "box:x"},
    )).status_code == 401


# ---- test-now --------------------------------------------------------- #


async def test_test_now_says_so_when_nothing_is_configured(client):
    body = (await client.post("/api/admin/backups/upload/test")).json()

    assert body["ok"] is False
    assert "configured" in body["detail"] or "backup on disk" in body["detail"]


async def test_a_failed_upload_is_recorded_as_a_failure(monkeypatch):
    """The count is what makes a quietly-broken upload visible.

    A local backup can succeed every night while the off-box copy has failed
    for a month, and only the second means the archive exists nowhere but the
    card it is protecting against.
    """
    from pathlib import Path

    await backup_service._run_upload_hook(
        Path("/tmp/nonexistent.tar.gz"), argv=["/nonexistent/uploader", "x"]
    )

    h = backup_service.health()
    assert h.upload_failures == 1
    assert h.last_upload_ok is False
    assert h.last_upload_error


async def test_a_successful_upload_is_recorded(tmp_path):
    payload = tmp_path / "b.tar.gz"
    payload.write_bytes(b"x")

    await backup_service._run_upload_hook(payload, argv=["/usr/bin/true"])

    h = backup_service.health()
    assert h.upload_successes == 1
    assert h.last_upload_ok is True
    assert h.last_upload_error is None

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


# ---- rsync and the NAS ------------------------------------------------ #
#
# One colon is a path on a host reached over SSH; TWO colons make rsync open a
# direct TCP connection to a daemon on port 873 and read the first segment as a
# MODULE name. They are different transports with different credentials, so the
# validator keeps them apart rather than accepting both under one pattern where
# a typo would silently switch which one runs.


async def test_an_ssh_destination_is_accepted_for_rsync():
    assert backup_service.validate_destination(
        "pi@nas.local:/volume1/backups/headroom", "rsync"
    ) == "pi@nas.local:/volume1/backups/headroom"


async def test_a_daemon_destination_is_accepted_for_synology():
    assert backup_service.validate_destination(
        "backup@synology.local::NetBackup/headroom", "synology"
    ) == "backup@synology.local::NetBackup/headroom"


async def test_a_daemon_destination_is_refused_for_plain_rsync():
    """The typo that matters.

    `user@host::module` under the SSH provider would have rsync talk to a
    daemon that expects an rsync-account password nobody configured, and the
    failure looks like a broken NAS rather than a wrong destination.
    """
    with pytest.raises(ValueError):
        backup_service.validate_destination("pi@nas.local::NetBackup/x", "rsync")


async def test_an_ssh_destination_is_refused_for_synology():
    with pytest.raises(ValueError):
        backup_service.validate_destination("pi@nas.local:/volume1/x", "synology")


async def test_an_rclone_remote_is_refused_for_rsync():
    """Each provider's pattern is its own; a remote name is not a host."""
    with pytest.raises(ValueError):
        backup_service.validate_destination("box:Headroom", "rsync")


@pytest.mark.parametrize("bad", [
    "-e ssh",                       # rsync's remote-shell flag
    "--rsh=/bin/sh",
    "pi@nas:/path; rm -rf /",
    "pi@nas:/path && curl evil",
])
async def test_rsync_refuses_flags_and_metacharacters(bad):
    with pytest.raises(ValueError):
        backup_service.validate_destination(bad, "rsync")


async def test_an_unknown_provider_is_refused_by_the_validator():
    with pytest.raises(ValueError, match="Unknown provider"):
        backup_service.validate_destination("pi@nas:/x", "bash")


async def test_the_rsync_argv_never_preserves_owner():
    """A NAS maps its own users and this container is uid 1000.

    Asking to preserve owner/group either errors or fills the log with
    warnings about an identity the destination was never going to honor.
    """
    for name in ("rsync", "synology"):
        argv = backup_service.UPLOAD_PROVIDERS[name].argv
        assert "--no-owner" in argv and "--no-group" in argv


async def test_the_destination_is_the_last_argv_slot_for_every_provider():
    """The safety property, restated across all three transports."""
    for spec in backup_service.UPLOAD_PROVIDERS.values():
        assert spec.argv.count("{dest}") == 1
        assert spec.argv[-1] == "{dest}"


# ---- the daemon password ---------------------------------------------- #


async def test_no_rsync_password_means_the_environment_is_inherited_unchanged(monkeypatch):
    monkeypatch.delenv("HEADROOM_BACKUP_RSYNC_PASSWORD", raising=False)
    assert backup_service.upload_env() is None


async def test_the_rsync_password_is_mapped_to_the_name_rsync_reads(monkeypatch):
    """rsync reads `RSYNC_PASSWORD`, not ours.

    Ours is namespaced so it can live in the same `.env` as everything else;
    the mapping is what makes it do anything.
    """
    monkeypatch.setenv("HEADROOM_BACKUP_RSYNC_PASSWORD", "hunter2")

    env = backup_service.upload_env()

    assert env is not None
    assert env["RSYNC_PASSWORD"] == "hunter2"


async def test_the_password_is_never_returned_by_the_api(client, monkeypatch):
    """A NAS password is not something this app should hand back over the wire.

    It is read from the host at upload time and deliberately never stored, so
    there is nothing here that could leak it.
    """
    monkeypatch.setenv("HEADROOM_BACKUP_RSYNC_PASSWORD", "hunter2")

    body = (await client.get("/api/admin/backups/upload")).json()

    assert "hunter2" not in str(body)
    # The variable is NAMED so the card can tell you what to set.
    syn = next(p for p in body["available_providers"] if p["name"] == "synology")
    assert syn["secret_env"] == "HEADROOM_BACKUP_RSYNC_PASSWORD"


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
    assert {p["name"] for p in body["available_providers"]} == {
        "rclone", "rsync", "synology",
    }


async def test_every_provider_ships_setup_steps(client):
    """The gap between "configured" and "working" is always host-side work.

    A card that can only say "not configured" leaves the operator to find the
    rsync account, the shared folder and the firewall rule on their own — and
    the failure when they miss one is an unattended upload that never runs.
    """
    body = (await client.get("/api/admin/backups/upload")).json()

    for p in body["available_providers"]:
        assert p["setup"], f"{p['name']} has no setup instructions"
        assert p["example"], f"{p['name']} has no example destination"
        assert p["destination_hint"], f"{p['name']} has no destination shape"


async def test_the_status_reports_whether_the_binary_is_actually_present(client, monkeypatch):
    """None of these binaries are in the base image.

    Reporting it is the difference between a card that says "configured" while
    every upload fails, and one that names the missing piece.
    """
    # Asserting the type only proved pydantic works. Drive the real lookup to
    # both answers and check each one actually reaches the payload — otherwise
    # a hardcoded `True` would pass, and a card reading "configured" while
    # every upload fails is the exact thing this field exists to prevent.
    monkeypatch.setattr(backup_service, "binary_available", lambda _b: False)
    body = (await client.get("/api/admin/backups/upload")).json()
    assert all(p["binary_available"] is False for p in body["available_providers"])

    monkeypatch.setattr(backup_service, "binary_available", lambda _b: True)
    body = (await client.get("/api/admin/backups/upload")).json()
    assert all(p["binary_available"] is True for p in body["available_providers"])


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


# ---- explaining a failure whose cause is elsewhere --------------------- #
#
# Reported from a real NAS: `@ERROR: Unknown module 'NetBackup'`. rsync's
# message is accurate and still leaves you stuck, because DSM has TWO rsync
# checkboxes and only "Enable network backup service" defines modules — the
# other is rsync over SSH. The setup steps said the wrong one.


async def test_an_unknown_module_is_explained_not_just_relayed():
    """Module names resolve BEFORE the password, so this is not credentials."""
    from headroom.routes.admin.backups import _explain

    out = _explain("exit 5: @ERROR: Unknown module 'NetBackup'")

    assert "Unknown module" in out, "the original error must survive"
    assert "network backup service" in out.lower()
    assert "not a credentials problem" in out.lower()


async def test_an_auth_failure_points_at_the_rsync_account():
    from headroom.routes.admin.backups import _explain

    out = _explain("@ERROR: auth failed on module NetBackup")

    assert "separate from your DSM login" in out


async def test_an_unrecognized_failure_is_passed_through_untouched():
    """No hint is better than a wrong hint."""
    from headroom.routes.admin.backups import _explain

    assert _explain("some novel disaster") == "some novel disaster"


async def test_the_synology_setup_names_the_right_checkbox():
    """The documentation bug that produced the report.

    'Enable rsync service' is SSH and defines no modules; only 'Enable network
    backup service' creates `NetBackup`. Getting this wrong sends someone to a
    checkbox that cannot work.
    """
    steps = " ".join(backup_service.UPLOAD_PROVIDERS["synology"].setup).lower()

    # Must tell the operator to LOOK, not assert a module name: DSM exposes
    # shared folders as modules, so the name varies per install.
    assert "do not assume it" in steps
    assert "enable network backup service" in steps
    assert "openrsync" in steps, "macOS rsync cannot do daemon syntax"


async def test_the_module_host_is_parsed_from_the_destination():
    """Enumeration targets the host, not the whole destination string."""
    import inspect

    src = inspect.getsource(backup_service.list_rsync_modules)

    # Anonymous by design: module listing precedes authentication, so no
    # credential should appear anywhere in that call.
    assert "RSYNC_PASSWORD" not in src
    assert "rsync://" in src


async def test_module_listing_never_raises_on_a_dead_host():
    """It only ever decorates an error message."""
    assert await backup_service.list_rsync_modules("u@127.0.0.1::x", timeout=1) == []
    assert await backup_service.list_rsync_modules("", timeout=1) == []

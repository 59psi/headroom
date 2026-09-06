"""The three failures that used to be silent across weeks of running.

A full disk, a dead background worker, and a scheduler whose history was
erased by the last restart. Each was invisible to everything the deployment
actually watches — the Docker healthcheck and the Settings screen — which is
what made them the interesting ones rather than the severe ones.
"""

from __future__ import annotations

import pytest

from headroom.services import analysis_queue, backup_service, import_service
from headroom.utils import disk

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _fresh_backup_health():
    """Two tests below mutate the process-local `BackupHealth`; every other
    backup test module carries this reset and this one did not, so a failing
    assertion here leaked `last_success_at` into whatever ran next."""
    from headroom.services import backup_service

    backup_service._health = backup_service.BackupHealth()
    yield
    backup_service._health = backup_service.BackupHealth()


# ---- free space ------------------------------------------------------- #


async def test_a_writable_volume_can_still_be_out_of_room(tmp_path, monkeypatch):
    """The readiness probe writes two bytes. Two bytes always fit.

    That is the whole bug: `uploads_writable` stayed green on a volume with
    8 KB free, while the next backup tarball, SQLite's WAL and every photo
    upload were already failing.
    """
    monkeypatch.setenv("HEADROOM_DISK_MIN_FREE_MB", "999999999")

    status = disk.check(tmp_path)

    assert status.ok is False
    assert (tmp_path / "probe").write_text("ok") == 2  # ...yet still writable


async def test_low_is_a_warning_and_not_a_failure(tmp_path, monkeypatch):
    """Two thresholds saying two different things: running out vs out."""
    monkeypatch.setenv("HEADROOM_DISK_WARN_PCT", "100")  # everything is "low"
    monkeypatch.setenv("HEADROOM_DISK_MIN_FREE_MB", "0")

    status = disk.check(tmp_path)

    assert status.low is True
    assert status.ok is True


async def test_a_broken_measurement_does_not_take_the_app_down(tmp_path):
    """A health signal that fails closed is worse than no signal.

    The error travels with the reading, so an authenticated caller sees why
    the numbers are missing instead of a confident zero.
    """
    status = disk.check(tmp_path / "does-not-exist")

    assert status.ok is True
    assert status.error is not None
    assert status.free_pct == 0.0


async def test_readiness_fails_when_the_disk_is_full(anon_client, monkeypatch):
    monkeypatch.setenv("HEADROOM_DISK_MIN_FREE_MB", "999999999")

    resp = await anon_client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json()["checks"]["disk"]["ok"] is False


async def test_anonymous_readiness_reports_disk_without_the_detail(anon_client):
    """The healthcheck needs the verdict; it does not need the capacity.

    Anonymous callers gate on booleans. Free bytes, total bytes and the
    configured floor are operational detail and stay behind auth, same as the
    filesystem path and the key source already did.
    """
    checks = (await anon_client.get("/health/ready")).json()["checks"]

    assert set(checks["disk"]) == {"ok", "low"}
    assert "path" not in checks["uploads_writable"]


async def test_authenticated_readiness_shows_the_numbers(client):
    checks = (await client.get("/health/ready")).json()["checks"]

    assert checks["disk"]["total_bytes"] > 0
    assert checks["disk"]["min_free_mb"] == disk.DEFAULT_MIN_FREE_MB


# ---- workers ---------------------------------------------------------- #


async def test_a_disabled_worker_is_not_a_dead_one(anon_client):
    """Tests run with both workers off; readiness must not scream about it.

    `worker_alive()` is False for a worker that died AND for one that was
    never started. Gating readiness on that alone would report unhealthy
    forever on any deliberately-degraded deployment — including this suite.
    """
    assert import_service.worker_expected() is False
    assert analysis_queue.worker_expected() is False

    resp = await anon_client.get("/health/ready")

    assert resp.status_code == 200
    assert resp.json()["checks"]["workers"]["ok"] is True


async def test_readiness_fails_when_an_expected_worker_is_dead(
    anon_client, monkeypatch
):
    """This is the check that lets the container go unhealthy.

    Before it, the container's health could not reflect a dead worker at all,
    because worker liveness was authenticated-only detail and the healthcheck
    is anonymous. (Docker's `restart: unless-stopped` never acts on health —
    only the host watchdog and the autoheal overlay do — which is why an
    accurate `unhealthy` matters: it is the signal they restart on.)
    """
    monkeypatch.setenv("HEADROOM_ANALYSIS_WORKER_ENABLED", "1")
    assert analysis_queue.worker_alive() is False  # ...but expected to be

    resp = await anon_client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json()["checks"]["workers"]["ok"] is False


async def test_an_import_job_with_no_worker_says_so_at_error(
    client, caplog, monkeypatch
):
    """Accepting work nothing will do is an ERROR, not a warning.

    Gated on the worker rather than on `_queue`: a queue with no consumer
    accepts `put_nowait` silently, so testing the queue caught the disabled
    case and missed the crashed one — where `_queue` is left non-None.
    """
    import io

    caplog.set_level("ERROR")
    files = [("photos", ("a.jpg", io.BytesIO(b"x" * 32), "image/jpeg"))]

    resp = await client.post("/api/hats/import", files=files)

    assert resp.status_code == 202
    assert any("no worker running" in r.getMessage() for r in caplog.records)


# ---- backup history --------------------------------------------------- #


async def test_last_success_falls_back_to_the_newest_backup(client, monkeypatch):
    """A restart must not turn "backed up an hour ago" into "never".

    The health record is process-local, and on this deployment restarts are
    routine — a restart policy, power cycles, and `docker compose up -d
    --build` as the documented upgrade. So the endpoint named health was the
    one that forgot.
    """
    from datetime import datetime, timezone

    backup_service.health().last_success_at = None
    stamp = datetime(2026, 5, 1, tzinfo=timezone.utc)

    async def _newest():
        return stamp

    monkeypatch.setattr(backup_service, "newest_backup_at", _newest)

    body = (await client.get("/api/admin/backups/health")).json()

    assert body["last_success_at"].startswith("2026-05-01")
    assert body["last_success_derived"] is True


async def test_a_real_recorded_success_is_not_flagged_as_derived(client, monkeypatch):
    """Derived means "a file exists", which is weaker than "a run succeeded".

    Collapsing the two would hide exactly the distinction the flag is for.
    """
    async def _newest():  # would win if the recorded value were ignored
        raise AssertionError("should not be consulted")

    monkeypatch.setattr(backup_service, "newest_backup_at", _newest)
    backup_service.health().record_success()

    body = (await client.get("/api/admin/backups/health")).json()

    assert body["last_success_derived"] is False
    assert body["last_success_at"] is not None


# ---- unhandled errors ------------------------------------------------- #


async def test_an_unhandled_error_becomes_an_activity_row(client, monkeypatch):
    """A 500 used to leave one trace: stdout, in a container, on a Pi.

    "Recent errors" only ever queried hats with analysis_status='error', so a
    route 500 appeared nowhere in the app at all.

    Fails a real route rather than registering a throwaway one — anything
    added after `create_app` is shadowed by the SPA catch-all, and a test that
    registers `/api/__boom` quietly asserts against index.html.
    """
    from headroom.routes import hats as hats_route

    def _boom(*a, **kw):
        raise RuntimeError("the roof")

    monkeypatch.setattr(hats_route.hat_service, "list_hats", _boom)

    with pytest.raises(RuntimeError):
        # Starlette sends this handler's response and then re-raises, so the
        # traceback still reaches the container log — the activity row joins
        # it rather than replacing it.
        await client.get("/api/hats")

    rows = (await client.get("/api/admin/activity-log?limit=50")).json()
    unhandled = [r for r in rows if r["kind"] == "error.unhandled"]

    assert len(unhandled) == 1
    assert "RuntimeError" in unhandled[0]["summary"]
    assert "/api/hats" in unhandled[0]["summary"]


async def test_the_error_row_records_the_path_but_not_the_query(client, monkeypatch):
    """Query strings carry search terms and tokens; the row is broadly readable."""
    from headroom.routes import hats as hats_route

    def _boom(*a, **kw):
        raise RuntimeError("nope")

    monkeypatch.setattr(hats_route.hat_service, "list_hats", _boom)

    with pytest.raises(RuntimeError):
        await client.get("/api/hats?q=hunter2")

    rows = (await client.get("/api/admin/activity-log?limit=50")).json()
    row = next(r for r in rows if r["kind"] == "error.unhandled")

    assert "hunter2" not in (row["details"] or "")
    assert "/api/hats" in (row["details"] or "")


async def test_the_error_row_redacts_a_share_token_from_the_path(client, monkeypatch):
    """The path-not-query rule above defeats itself on exactly one route.

    A share token is a 256-bit bearer credential and it is a PATH parameter,
    so for `/api/public/share/{token}` the thing being recorded "because it is
    safer than the query string" IS the credential. Both sinks are durable and
    one of them is the database, which the scheduled backup uploads off the
    box — so an unredacted row hands a live token to whatever NAS or cloud
    remote holds the archive, for as long as it is retained.

    The route must stay legible: which endpoint 500'd is the most useful field
    on an error row, so this redacts the token and keeps the path.
    """
    from headroom.routes import share_links as share_links_route

    token = "Ab3d-Ef7h_Ij1k2Lm3n4Op5q"

    async def _boom(*a, **kw):
        raise RuntimeError("resolve blew up")

    monkeypatch.setattr(share_links_route.share_link_service, "resolve_token", _boom)

    with pytest.raises(RuntimeError):
        await client.get(f"/api/public/share/{token}")

    rows = (await client.get("/api/admin/activity-log?limit=50")).json()
    row = next(r for r in rows if r["kind"] == "error.unhandled")

    assert token not in (row["details"] or ""), "a live share token reached the database"
    assert token not in (row["summary"] or ""), "a live share token reached the summary"
    assert "<redacted>" in (row["details"] or "")
    assert "/api/public/share/" in (row["details"] or ""), (
        "the route was thrown away along with the token"
    )


# ---- effective configuration ------------------------------------------ #


async def test_the_config_endpoint_reports_what_the_code_will_do(client):
    """Not what a file says — what the next call will actually use.

    Every toggle here is an env var read live, and `env_int`/`env_flag`
    degrade a typo to the default rather than crashing. That is the right
    trade, and it means a misconfigured box looks identical to a correct one
    from outside. This is where the difference becomes visible.
    """
    body = (await client.get("/api/admin/config")).json()

    assert body["backups"]["keep"] == backup_service.backup_keep()
    assert body["workers"]["analysis"]["expected"] is False  # disabled in tests
    assert body["limits"]["disk_min_free_mb"] == disk.DEFAULT_MIN_FREE_MB
    assert body["storage"]["total_bytes"] > 0


async def test_a_typo_shows_up_as_the_default_it_silently_became(client, monkeypatch):
    monkeypatch.setenv("HEADROOM_BACKUP_KEEP", "five")

    body = (await client.get("/api/admin/config")).json()

    assert body["backups"]["keep"] == 5  # not "five", and not a 500


async def test_the_config_endpoint_reports_the_model_the_code_will_use(client):
    """EFFECTIVE means resolved. The endpoint reported the environment default
    while every caller resolves the model through the DB-first lookup, so a
    model chosen in Settings made this endpoint name the wrong one."""
    before = (await client.get("/api/admin/config")).json()
    assert before["model_source"] in ("default", "environment", "env")

    assert (
        await client.put("/api/settings/model", json={"model_id": "claude-opus-5"})
    ).status_code == 200

    after = (await client.get("/api/admin/config")).json()
    assert after["model"] == "claude-opus-5"
    assert after["model_source"] == "database"


async def test_the_config_endpoint_sees_an_upload_provider_configured_in_the_ui(client, monkeypatch):
    """`off_box_upload_configured` counted only the env command and ignored a
    provider set up in Settings — so the one endpoint meant to say "is there a
    copy of my data leaving this card" said no to a working configuration."""
    monkeypatch.delenv("HEADROOM_BACKUP_UPLOAD_CMD", raising=False)
    assert (await client.get("/api/admin/config")).json()["backups"][
        "off_box_upload_configured"
    ] is False

    resp = await client.put(
        "/api/admin/backups/upload",
        json={"provider": "rsync", "destination": "pi@nas.local:/volume1/headroom"},
    )
    assert resp.status_code == 200, resp.text

    assert (await client.get("/api/admin/config")).json()["backups"][
        "off_box_upload_configured"
    ] is True


async def test_the_config_endpoint_leaks_no_secrets(client):
    """Key presence is the key-status endpoints' job; repeating it here would
    be a second place to keep the same redaction correct."""
    text = (await client.get("/api/admin/config")).text.lower()

    for forbidden in ("sk-ant", "api_key", "secret", "token", "password"):
        assert forbidden not in text



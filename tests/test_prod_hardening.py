"""Regression tests for the production-hardening fixes (code-archaeology pass).

Each test locks in a specific finding's fix; the diagnosis flagged all of these
paths as previously untested.
"""

import os
import time

import pytest

pytestmark = pytest.mark.anyio


async def _make_hat(client, **extra):
    payload = {"condition": "new", "size": "classic", "style": "a_game", **extra}
    resp = await client.post("/api/hats", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- R4: undispose must reassign position, not collide ------------------- #


async def test_undispose_reassigns_position_no_collision(client):
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    h1 = await _make_hat(client, case_id=case["id"])
    h2 = await _make_hat(client, case_id=case["id"])
    assert h1["position_in_case"] == 1
    assert h2["position_in_case"] == 2

    # Dispose h2, freeing slot 2; a new hat then takes that slot number.
    await client.post(f"/api/hats/{h2['id']}/dispose", json={"via": "sold"})
    h3 = await _make_hat(client, case_id=case["id"])
    assert h3["position_in_case"] == 2

    # Undispose h2 — it must NOT reclaim its stale position 2 (h3 has it now).
    restored = (await client.delete(f"/api/hats/{h2['id']}/dispose")).json()
    assert restored["position_in_case"] != h3["position_in_case"]
    assert restored["position_in_case"] == 3
    assert restored["display_id"] != h3["display_id"]

    # No two active hats in the case share a position/display_id.
    active = (await client.get(f"/api/hats?case_id={case['id']}")).json()
    positions = [h["position_in_case"] for h in active]
    assert len(positions) == len(set(positions)), positions


# --- R12: PUT /colors must normalize general_color ---------------------- #


async def test_put_colors_normalizes_general_color(client):
    from headroom.services.color_extraction import normalize_hex_name

    hat = await _make_hat(client)
    resp = await client.put(
        f"/api/hats/{hat['id']}/colors",
        json={"colors": [{
            "color_name": "heather slate",
            "general_color": "totally-bogus-name",
            "hex_value": "#ff0000",
            "dominance_rank": 1,
            "tier": "primary",
        }]},
    )
    assert resp.status_code == 200, resp.text
    color = resp.json()["colors"][0]
    # Stored general_color is snapped to the palette from the hex, not the
    # client's free-text — so it stays searchable by the color chips.
    assert color["general_color"] != "totally-bogus-name"
    assert color["general_color"] == normalize_hex_name("#ff0000", "heather slate")


# --- wear log idempotency (Doppler) ------------------------------------- #


async def test_wear_idempotent_same_day(client):
    hat = await _make_hat(client)
    first = (await client.post(f"/api/hats/{hat['id']}/wear", json={})).json()
    second = (await client.post(f"/api/hats/{hat['id']}/wear", json={})).json()
    assert first["wear_count"] == 1
    assert second["wear_count"] == 1  # second same-day tap is a no-op


# --- S3: password change rotates the API token -------------------------- #


async def test_password_change_rotates_api_token(client):
    before = (await client.get("/api/auth/me")).json()["api_token"]
    resp = await client.post(
        "/api/auth/password",
        json={"current_password": "test-password-123", "new_password": "new-password-456"},
    )
    assert resp.status_code == 204, resp.text
    after = (await client.get("/api/auth/me")).json()["api_token"]
    assert after != before


# --- S4: failed login is audited ---------------------------------------- #


async def test_failed_login_writes_audit_row(client):
    r = await client.post(
        "/api/auth/login", json={"username": "testowner", "password": "wrong-password"}
    )
    assert r.status_code == 401
    rows = (await client.get("/api/admin/activity-log?kind=auth.login_failed")).json()
    assert any(row["kind"] == "auth.login_failed" for row in rows), rows


# --- S2/R9: /health/ready redacts detail for anonymous callers ---------- #


async def test_health_ready_redacts_for_anonymous(anon_client):
    body = (await anon_client.get("/health/ready")).json()
    key_check = body["checks"]["anthropic_key"]
    assert "source" not in key_check           # no key source leaked
    assert "path" not in body["checks"]["uploads_writable"]  # no fs path leaked
    assert "import_worker" not in body["checks"]  # operational detail hidden


async def test_health_ready_full_detail_for_authenticated(client):
    body = (await client.get("/health/ready")).json()
    assert "source" in body["checks"]["anthropic_key"]
    assert "path" in body["checks"]["uploads_writable"]
    assert "import_worker" in body["checks"]


# --- public branding logo (login page); settings logo stays gated ------- #


async def test_public_branding_logo_is_ungated(anon_client):
    from headroom.config import settings

    (settings.upload_dir / "branding" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    resp = await anon_client.get("/api/public/branding/logo")
    assert resp.status_code == 200
    # The management logo endpoint is still auth-gated for anonymous callers.
    gated = await anon_client.get("/api/settings/logo")
    assert gated.status_code == 401


async def test_public_branding_logo_404_when_absent(anon_client):
    resp = await anon_client.get("/api/public/branding/logo")
    assert resp.status_code == 404


# --- S5: first-run setup blocks a second owner -------------------------- #


async def test_setup_blocks_second_owner(anon_client):
    ok = await anon_client.post(
        "/api/auth/setup", json={"username": "owner1", "password": "password-123"}
    )
    assert ok.status_code == 200
    again = await anon_client.post(
        "/api/auth/setup", json={"username": "owner2", "password": "password-456"}
    )
    assert again.status_code == 403


# --- R2: backup retention is age-based, keeps the newest ---------------- #


def _make_backup(name_ts: str, age_days: float):
    from headroom.services import backup_service

    p = backup_service._backup_dir() / (
        f"{backup_service.BACKUP_PREFIX}{name_ts}{backup_service.BACKUP_SUFFIX}"
    )
    p.write_bytes(b"x")
    when = time.time() - age_days * 86400
    os.utime(p, (when, when))
    return p


async def test_backup_retention_prunes_by_age_keeps_newest():
    from headroom.services import backup_service

    old = _make_backup("2020-01-01T00-00-00Z", age_days=30)
    recent = _make_backup("2026-07-15T00-00-00Z", age_days=1)
    backup_service._enforce_retention(7)
    assert not old.exists()      # older than 7 days → pruned
    assert recent.exists()       # within window → kept


async def test_backup_retention_never_deletes_the_only_backup():
    from headroom.services import backup_service

    lonely = _make_backup("2019-01-01T00-00-00Z", age_days=999)
    backup_service._enforce_retention(7)
    assert lonely.exists()  # never leave zero backups on disk


async def test_backup_startup_skip_signal():
    from headroom.services import backup_service

    assert backup_service._seconds_since_newest_backup_sync() is None
    _make_backup("2026-07-15T12-00-00Z", age_days=0)
    age = backup_service._seconds_since_newest_backup_sync()
    assert age is not None and age < 3600  # a recent backup exists → skip startup one


# --- R5: import boot-sweep heals crash-stranded state ------------------- #


async def test_import_boot_sweep_recovers_processing_and_closes_terminal(monkeypatch):
    from tests.conftest import test_session_factory

    from headroom.models.import_job import ImportJob, ImportJobItem
    from headroom.services import import_service

    # The worker uses the production session factory; point it at the test DB.
    monkeypatch.setattr(
        "headroom.services.import_service.async_session", test_session_factory
    )

    async with test_session_factory() as db:
        # Job A: crashed mid-flight — one 'processing' item left dangling.
        job_a = ImportJob(total=1, status="running")
        db.add(job_a)
        await db.flush()
        db.add(ImportJobItem(job_id=job_a.id, filename="a.jpg", status="processing"))
        # Job B: every item already terminal (e.g. all oversize) but never closed.
        job_b = ImportJob(total=2, status="queued", errors=0)
        db.add(job_b)
        await db.flush()
        db.add(ImportJobItem(job_id=job_b.id, filename="b1.jpg", status="error"))
        db.add(ImportJobItem(job_id=job_b.id, filename="b2.jpg", status="error"))
        await db.commit()
        job_a_id, job_b_id = job_a.id, job_b.id

    await import_service._recover_on_boot()

    async with test_session_factory() as db:
        from sqlalchemy import select

        item_a = (await db.execute(
            select(ImportJobItem).where(ImportJobItem.job_id == job_a_id)
        )).scalar_one()
        assert item_a.status == "queued"  # re-queued for retry, not stranded

        job_b = await db.get(ImportJob, job_b_id)
        assert job_b.status == "done"     # all-terminal job closed
        assert job_b.errors == 2

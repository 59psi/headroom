"""Tests for the admin endpoints (recent errors + backup) and model setting."""

import pytest

pytestmark = pytest.mark.anyio


# ---- Model setting -------------------------------------------------- #


async def test_get_model_returns_default_when_unset(client):
    resp = await client.get("/api/settings/model")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_id"]  # non-empty
    assert body["source"] in ("default", "environment")


async def test_set_model_persists(client):
    # Deliberately not the configured default, so "source: database" is proved
    # by the write rather than coincidentally true.
    resp = await client.put("/api/settings/model", json={"model_id": "claude-opus-5"})
    assert resp.status_code == 200
    assert resp.json() == {"model_id": "claude-opus-5", "source": "database"}

    # GET reflects the change
    resp = await client.get("/api/settings/model")
    assert resp.json()["model_id"] == "claude-opus-5"
    assert resp.json()["source"] == "database"


async def test_clear_model_falls_back_to_default(client):
    await client.put("/api/settings/model", json={"model_id": "claude-opus-5"})
    resp = await client.delete("/api/settings/model")
    assert resp.status_code == 204
    resp = await client.get("/api/settings/model")
    assert resp.json()["source"] in ("default", "environment")


async def test_set_model_validates_length(client):
    resp = await client.put("/api/settings/model", json={"model_id": "ab"})  # too short
    assert resp.status_code == 422


# ---- Recent errors -------------------------------------------------- #


async def test_recent_errors_empty_initially(client):
    resp = await client.get("/api/admin/recent-errors")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_recent_errors_count_endpoint(client):
    resp = await client.get("/api/admin/recent-errors/count")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0}


async def test_the_badge_sees_a_failure_that_is_not_status_error(client, db_session):
    """The outage case. `fallback` is a failure and used to be invisible.

    Both endpoints keyed on `analysis_status == "error"`. When Claude is
    unreachable the pipeline does not set `error` — it degrades, writes the
    reason, and sets **`fallback`**. So in the one situation where every hat in
    the collection has failed, the nav badge read 0 and the error list was
    empty, while the analysis-failures card listed all of them.

    `skipped` (no API key configured) has the same shape and is included for
    the same reason: it carries a reason and it wants retrying.

    `failed_analysis_filters()` — the predicate whose own docstring explains
    that keying on status "would not work" — was already in `hat_service` when
    these two routes were written against status anyway.
    """
    from headroom.models.hat import Hat

    db_session.add(Hat(
        condition="new", size="classic", style="a_game",
        analysis_status="fallback", analysis_error="529 Overloaded",
    ))
    db_session.add(Hat(
        condition="new", size="classic", style="a_game",
        analysis_status="skipped", analysis_error="No API key configured.",
    ))
    # Succeeded: no failure text, so it must NOT be counted however it is
    # labelled — the text is what gets cleared on success.
    db_session.add(Hat(
        condition="new", size="classic", style="a_game",
        analysis_status="ok", analysis_error=None,
    ))
    await db_session.commit()

    assert (await client.get("/api/admin/recent-errors/count")).json() == {"count": 2}
    rows = (await client.get("/api/admin/recent-errors")).json()
    assert {r["analysis_error"] for r in rows} == {
        "529 Overloaded", "No API key configured.",
    }, "the badge and the list must describe the same set"


# ---- Backup --------------------------------------------------------- #


async def test_backup_download_returns_gzip_attachment(client):
    import io
    import tarfile

    resp = await client.get("/api/admin/backup")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert "attachment" in resp.headers["content-disposition"]

    # "Looks like a gzip" (right magic bytes, non-trivial length) is not "is a
    # restorable backup". Actually open the payload as a gzip tar and walk it —
    # a truncated or corrupt stream passes a length check but blows up here.
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        names = tar.getnames()
    # The uploads tree is always captured (the autouse fixture points
    # upload_dir at a real temp dir); everything is rooted under data/ so a
    # restore lands in the right place.
    assert names, "backup archive is empty"
    assert all(n == "data" or n.startswith("data/") for n in names), names
    assert any(n == "data/uploads" or n.startswith("data/uploads/") for n in names), names


async def test_list_backups_empty_initially(client):
    resp = await client.get("/api/admin/backups")
    assert resp.status_code == 200
    assert resp.json() == []


# ---- Admin auth gate ------------------------------------------------ #


async def test_admin_endpoints_require_auth(client, anon_client):
    """v1.0: admin routes need a session cookie or a bearer API token."""
    # Anonymous → 401 (client fixture seeds the owner; anon has no cookie)
    resp = await anon_client.get("/api/admin/recent-errors")
    assert resp.status_code == 401

    # Wrong bearer token → 401
    resp = await anon_client.get(
        "/api/admin/recent-errors", headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 401

    # Valid session cookie → 200
    resp = await client.get("/api/admin/recent-errors")
    assert resp.status_code == 200

    # Valid API token (the seeded owner's) → 200
    resp = await anon_client.get(
        "/api/admin/recent-errors",
        headers={"Authorization": "Bearer hr_test-api-token"},
    )
    assert resp.status_code == 200

"""Operator knobs and inputs at their edges — each one executed and wrong.

`HEADROOM_REPRICING_INTERVAL_HOURS=nan` killed the re-pricing scheduler on
its first sleep; `HEADROOM_MAX_BODY_BYTES=0` made every POST a 413 including
the login; `HEADROOM_BACKUP_RETENTION_DAYS=0` switched retention off where
the primary knob would have fallen back; a tag base of `http://` was stored as
`http:`; `?q=%` matched the whole shelf; a hand-edited upload marker hydrated
a string into a boolean field.
"""

from __future__ import annotations

import json

import pytest

from headroom.config import env_float
from headroom.limits import DEFAULT_MAX_BODY_BYTES, max_body_bytes
from headroom.services import backup_service

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e400", "abc", ""])
async def test_a_non_finite_or_unparseable_float_knob_is_its_default(monkeypatch, raw):
    monkeypatch.setenv("HEADROOM_PROBE_FLOAT", raw)
    assert env_float("HEADROOM_PROBE_FLOAT", 24.0) == 24.0


async def test_a_real_float_knob_is_read(monkeypatch):
    monkeypatch.setenv("HEADROOM_PROBE_FLOAT", "0.5")
    assert env_float("HEADROOM_PROBE_FLOAT", 24.0) == 0.5


@pytest.mark.parametrize("raw", ["0", "-1", "512"])
async def test_a_body_cap_nothing_can_fit_through_is_the_default(monkeypatch, raw):
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", raw)
    assert max_body_bytes() == DEFAULT_MAX_BODY_BYTES


async def test_a_login_still_fits_under_a_zeroed_body_cap(anon_client, monkeypatch):
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "0")
    resp = await anon_client.post("/api/auth/login", json={"username": "x", "password": "y" * 8})
    assert resp.status_code != 413


@pytest.mark.parametrize("raw", ["0", "-5"])
async def test_the_legacy_retention_knob_cannot_switch_pruning_off(monkeypatch, raw):
    monkeypatch.delenv("HEADROOM_BACKUP_KEEP", raising=False)
    monkeypatch.setenv("HEADROOM_BACKUP_RETENTION_DAYS", raw)
    assert backup_service.backup_keep() == 5


async def test_a_hand_edited_upload_marker_cannot_hydrate_the_wrong_types(
    isolated_upload_dir, monkeypatch
):
    backup_service._backup_dir().mkdir(parents=True, exist_ok=True)
    backup_service._upload_state_path().write_text(json.dumps({
        "ok": "yes", "name": 42, "error": ["not", "a", "string"], "successes": "3", "at": "junk",
    }))
    record = backup_service.BackupHealth()
    monkeypatch.setattr(backup_service, "_upload_state_loaded", False)
    backup_service._ensure_upload_state_loaded(record)
    assert record.last_upload_ok is None
    assert record.last_upload_name is None
    assert record.last_upload_error is None
    assert record.upload_successes == 0
    assert record.last_upload_at is None


@pytest.mark.parametrize("bad", ["http://", "https://", "http:///t/h/1", "http://user:pw@host"])
async def test_a_tag_base_must_name_a_host(client, bad):
    resp = await client.put("/api/settings/tags", json={"base_url": bad})
    assert resp.status_code == 422, resp.text


async def test_search_treats_like_wildcards_as_text(client):
    for name in ("Odysea Hydro", "A-Game Hydro", "100% Wool"):
        await client.post(
            "/api/hats",
            json={"condition": "new", "size": "classic", "style": "a_game", "model_name": name},
        )
    hits = (await client.get("/api/search?q=%25")).json()
    assert [h["model_name"] for h in hits] == ["100% Wool"]
    hits = (await client.get("/api/search?q=a_game")).json()
    assert len(hits) == 3, "the style enum value matches every a_game hat"
    hits = (await client.get("/api/search?q=y_ea")).json()
    assert hits == [], "`_` is not a single-character wildcard"


async def test_search_matches_the_style_as_it_is_printed(client):
    """The enum value is `a_game`; the option, every list and the hint under
    the search box print `A-Game`, and a search for that found nothing."""
    for style in ("a_game", "odysea"):
        await client.post(
            "/api/hats", json={"condition": "new", "size": "classic", "style": style}
        )
    for term in ("A-Game", "a-game", "Game"):
        hits = (await client.get(f"/api/search?q={term}")).json()
        assert [h["style"] for h in hits] == ["a_game"], term
    hits = (await client.get("/api/search?q=Odysea")).json()
    assert [h["style"] for h in hits] == ["odysea"]

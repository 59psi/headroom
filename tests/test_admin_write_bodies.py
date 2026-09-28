"""The admin and settings write paths validate what they write, and say what they did.

Each of these accepted something a sibling path refused, or answered with
something other than what it stored: a list parameter read from a body the
client never sent, a construction the hat form would have rejected, pasted
quotes stored as a credential, a price of 1e308, a tag host with a path in it.
"""

from __future__ import annotations

import io
import json

import pytest

from headroom.services import backup_service, ebay_service, settings_service

pytestmark = pytest.mark.anyio


async def _hat(client, **overrides) -> int:
    hat_id = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()["id"]
    if overrides:
        resp = await client.put(f"/api/hats/{hat_id}", json=overrides)
        assert resp.status_code == 200, resp.text
    return hat_id


async def _rows(client, kind: str) -> list[dict]:
    rows = (await client.get("/api/admin/activity-log?limit=100")).json()
    return [r for r in rows if r["kind"] == kind]


# ---- frozen prices ----------------------------------------------------- #


async def test_releasing_one_frozen_price_releases_only_that_one(client):
    """Exactly what the card sends for one ticked row. `hat_ids` was a BODY
    parameter, so the query string was never read, the list arrived as None
    ("every frozen hat") and one tick released them all."""
    keep = await _hat(client, resale_price=60.0)
    release = await _hat(client, resale_price=52.5)

    resp = await client.post(
        f"/api/admin/prices/release?dry_run=false&market_priced_only=false&hat_ids={release}"
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["released"] == 1
    assert (await client.get(f"/api/hats/{release}")).json()["resale_price_scope"] is None
    assert (await client.get(f"/api/hats/{keep}")).json()["resale_price_scope"] == "manual"


# ---- constructions ----------------------------------------------------- #


async def test_the_bulk_construction_write_obeys_the_hat_forms_rule(client):
    """`to` is written onto every matching hat; it took what `PUT /api/hats`
    would refuse — a bidi override, a NUL, 300 characters."""
    await _hat(client, construction="Wool Blend")

    too_long = await client.post(
        "/api/admin/constructions/clear",
        params={"value": "Wool Blend", "to": "\u202eevil" + "X" * 300, "dry_run": "false"},
    )
    assert too_long.status_code == 422

    cleaned = await client.post(
        "/api/admin/constructions/clear",
        params={"value": "Wool Blend", "to": "\u202eThermal\u0000", "dry_run": "false",
                "skip_owner_set": "false"},
    )
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["to"] == "Thermal"


async def test_the_construction_audit_row_is_structured(client):
    """The details were a sentence JSON-encoded into a quoted string."""
    await _hat(client, construction="Wool Blend")

    await client.post(
        "/api/admin/constructions/clear",
        params={"value": "Wool Blend", "to": "Thermal", "dry_run": "false",
                "skip_owner_set": "false"},
    )

    row = (await _rows(client, "construction.cleared"))[0]
    details = json.loads(row["details"])
    assert isinstance(details, dict)
    assert set(details) >= {"model_names_corrected", "manual_prices_kept"}


# ---- off-box upload ---------------------------------------------------- #


async def _store_a_destination_that_no_longer_validates(db_session):
    await settings_service.set_setting(db_session, backup_service.UPLOAD_PROVIDER_KEY, "rclone")
    await settings_service.set_setting(
        db_session, backup_service.UPLOAD_DESTINATION_KEY, "--config=/etc/x"
    )
    await db_session.commit()


async def test_the_config_endpoint_reports_a_broken_destination_as_configured(
    client, db_session, monkeypatch
):
    """It caught `ValueError`; the error is `UploadConfigError`. So the endpoint
    built to show an operator this exact state answered 500 in it."""
    monkeypatch.delenv("HEADROOM_BACKUP_UPLOAD_CMD", raising=False)
    await _store_a_destination_that_no_longer_validates(db_session)

    resp = await client.get("/api/admin/config")

    assert resp.status_code == 200, resp.text
    assert resp.json()["backups"]["off_box_upload_configured"] is True


async def test_a_stored_provider_this_build_does_not_know_is_still_configured(
    client, db_session, monkeypatch
):
    """Configured means "someone set one up", not "it would run". The route
    asked `resolve_upload_argv` to build a command and read the answer off
    its failure mode — and for a provider name this build does not know, that
    is None, the same None as "nothing configured"."""
    monkeypatch.delenv("HEADROOM_BACKUP_UPLOAD_CMD", raising=False)
    await settings_service.set_setting(db_session, backup_service.UPLOAD_PROVIDER_KEY, "ftp")
    await settings_service.set_setting(
        db_session, backup_service.UPLOAD_DESTINATION_KEY, "nas.local:/backups"
    )
    await db_session.commit()

    body = (await client.get("/api/admin/config")).json()

    assert body["backups"]["off_box_upload_configured"] is True


async def test_the_config_endpoint_reports_the_backup_cadence_that_runs(client, monkeypatch):
    """The scheduler floors its interval at a minute; the endpoint reported
    the raw knob, so `0.001` read as a 3.6-second cadence nothing ran."""
    monkeypatch.setenv("HEADROOM_BACKUP_INTERVAL_HOURS", "0.001")

    body = (await client.get("/api/admin/config")).json()

    assert body["backups"]["interval_hours"] == pytest.approx(1 / 60)


async def test_test_now_explains_a_broken_destination_instead_of_500ing(
    client, db_session, monkeypatch, tmp_path
):
    monkeypatch.delenv("HEADROOM_BACKUP_UPLOAD_CMD", raising=False)
    (tmp_path / "bk").mkdir()
    (tmp_path / "bk" / backup_service._timestamped_name()).write_bytes(b"tarball")
    monkeypatch.setattr(backup_service, "_backup_dir", lambda: tmp_path / "bk")
    await _store_a_destination_that_no_longer_validates(db_session)

    resp = await client.post("/api/admin/backups/upload/test")

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is False
    assert "no longer validates" in resp.json()["detail"]


async def test_clearing_the_upload_leaves_no_provider_behind(client):
    await client.put(
        "/api/admin/backups/upload", json={"provider": "rclone", "destination": "box:Headroom"}
    )

    body = (await client.delete("/api/admin/backups/upload")).json()

    assert body["configured"] is False
    assert body["provider"] is None and body["destination"] is None


# ---- eBay credentials -------------------------------------------------- #


async def test_pasted_quotes_around_spaces_are_not_a_credential(client):
    """Quotes stripped after the whitespace left four spaces, stored, and
    reported back as `configured: true`."""
    resp = await client.put(
        "/api/admin/ebay/creds",
        json={"app_id": "'    '", "cert_id": '"    "'},
    )

    assert resp.status_code == 422
    assert (await client.get("/api/admin/ebay/creds")).json()["configured"] is False


async def test_a_quoted_paste_is_unwrapped_before_it_is_stored(client, db_session):
    resp = await client.put(
        "/api/admin/ebay/creds",
        json={"app_id": " 'Me-App-PRD-1234-5678' ", "cert_id": '"PRD-cert-9999"',
              "marketplace": " ebay_gb "},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["configured"] is True
    assert resp.json()["marketplace"] == "EBAY_GB"
    assert await settings_service.get_setting(db_session, ebay_service.EBAY_APP_ID_KEY) == (
        "Me-App-PRD-1234-5678"
    )


@pytest.mark.parametrize(
    "bad", ["Me-App\u200bPRD-1234", "Me-App PRD-1234", "Me-App\x00PRD-1234", "Me-App-PRD-é1234"],
    ids=["zero-width-space", "inner-space", "nul", "non-ascii"],
)
async def test_an_ebay_key_no_header_can_carry_is_refused(client, bad):
    """Both halves go into the OAuth request's authorization header, which
    holds printable ASCII only — so a key that cannot is refused at Save,
    not stored to fail every refresh after it."""
    resp = await client.put(
        "/api/admin/ebay/creds", json={"app_id": bad, "cert_id": "PRD-cert-9999"},
    )
    assert resp.status_code == 422, resp.text
    resp = await client.put(
        "/api/admin/ebay/creds", json={"app_id": "Me-App-PRD-1234", "cert_id": bad},
    )
    assert resp.status_code == 422, resp.text
    assert (await client.get("/api/admin/ebay/creds")).json()["configured"] is False


@pytest.mark.parametrize("path", ["/api/settings/api-key", "/api/settings/google-vision-key"])
@pytest.mark.parametrize(
    "bad", ["AIza\u202eSy-1234567890", "AIzaSy 1234567890", "AIzaSy-1234\x00567890"],
    ids=["bidi-override", "inner-space", "nul"],
)
async def test_an_api_key_no_header_can_carry_is_refused(client, path, bad):
    resp = await client.put(path, json={"api_key": bad})

    assert resp.status_code == 422, resp.text
    assert "printable ASCII" in resp.text
    assert (await client.get(path)).json()["configured"] is False


async def test_a_pasted_key_is_trimmed_not_refused(client, db_session):
    resp = await client.put("/api/settings/google-vision-key", json={"api_key": "  AIzaSy-1234567890\n"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["configured"] is True


async def test_a_marketplace_must_be_one_ebay_has(client):
    resp = await client.put(
        "/api/admin/ebay/creds",
        json={"app_id": "Me-App-PRD-1", "cert_id": "PRD-cert-1", "marketplace": "<b>NOPE</b>"},
    )

    assert resp.status_code == 422


@pytest.mark.parametrize("spelling", ["", "   ", " ebay_gb "], ids=["empty", "spaces", "lower"])
async def test_a_marketplace_is_read_the_way_the_route_always_read_it(client, spelling):
    """Blank still means the default, as `.strip() or "EBAY_US"` did before
    the enum, and a lower-case id is still that id — the vocabulary closed,
    and nothing a client used to send got a new 422 for it."""
    resp = await client.put(
        "/api/admin/ebay/creds",
        json={"app_id": "Me-App-PRD-1", "cert_id": "PRD-cert-1", "marketplace": spelling},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["marketplace"] == (spelling.strip().upper() or "EBAY_US")


async def test_the_put_reports_what_it_stored_not_a_constant(client, monkeypatch):
    """`configured=True` was hardcoded in the PUT's answer."""

    async def _no_cert(_db):
        return "Me-App-PRD-1", None, "EBAY_US"

    monkeypatch.setattr(ebay_service, "get_creds", _no_cert)

    resp = await client.put(
        "/api/admin/ebay/creds", json={"app_id": "Me-App-PRD-1", "cert_id": "PRD-cert-1"}
    )

    assert resp.json()["configured"] is False


async def test_clearing_the_credentials_clears_the_marketplace(client, db_session):
    await client.put(
        "/api/admin/ebay/creds",
        json={"app_id": "Me-App-PRD-1", "cert_id": "PRD-cert-1", "marketplace": "EBAY_DE"},
    )

    await client.delete("/api/admin/ebay/creds")

    assert await settings_service.get_setting(db_session, ebay_service.EBAY_MARKETPLACE_KEY) is None
    assert (await client.get("/api/admin/ebay/creds")).json()["marketplace"] == "EBAY_US"


async def test_an_ebay_refresh_persists_what_it_returns(client, monkeypatch):
    """The route used to echo the service's dict; dropping the write onto the
    hat still returned prices that were never saved."""
    from datetime import datetime, timezone

    hat_id = await _hat(client, brand="Melin", model_name="Odysea")

    async def _comps(_db, **_kw):
        return {
            "ebay_avg_price": 71.0, "ebay_median_price": 70.0, "ebay_listing_count": 3,
            "ebay_search_url": "https://www.ebay.com/sch/i.html?_nkw=melin",
            "ebay_checked_at": datetime.now(timezone.utc),
        }

    monkeypatch.setattr(ebay_service, "find_comps", _comps)

    resp = await client.post(f"/api/admin/ebay/refresh/{hat_id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["ebay_median_price"] == 70.0
    # Every column of the block, as STORED: re-read off the hat, compared to
    # what the response claimed.
    stored = (await client.get(f"/api/hats/{hat_id}")).json()
    for field in ("ebay_avg_price", "ebay_median_price", "ebay_listing_count",
                  "ebay_search_url", "ebay_checked_at"):
        assert stored[field] == resp.json()[field], field
    assert stored["ebay_listing_count"] == 3


# ---- purchase lines ---------------------------------------------------- #


async def test_a_purchase_price_is_money(client):
    """`PurchaseLine.price` restated `Money` without its upper bound, and a
    `1e308` line became a hat's cost basis."""
    resp = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "Odysea", "price": 1e308}]},
    )

    assert resp.status_code == 422


async def test_purchase_text_is_cleaned_and_capped(client):
    ok = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "Odysea\u202e\u0000", "colorway": "\u202eetihW",
                         "price": 69.0, "order_ref": "#1001"}]},
    )
    assert ok.status_code == 200, ok.text
    line = (await client.get("/api/admin/purchases")).json()[0]
    assert line["item_title"] == "Odysea"
    assert line["colorway"] == "etihW"

    too_long = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "x" * 201}]},
    )
    assert too_long.status_code == 422


# ---- settings ---------------------------------------------------------- #


async def test_every_settings_change_is_audited(client):
    """The keys and the guest switch were logged; the model, the tag host —
    which decides where every printed label points — and the logo were not."""
    await client.put("/api/settings/model", json={"model_id": "claude-test-1"})
    await client.delete("/api/settings/model")
    await client.put("/api/settings/tags", json={"base_url": "http://headroom.local:8000"})
    await client.delete("/api/settings/tags")
    buf = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (32, 32), (200, 30, 90)).save(buf, "PNG")
    await client.post(
        "/api/settings/logo", files={"photo": ("logo.png", buf.getvalue(), "image/png")}
    )
    await client.delete("/api/settings/logo")

    kinds = {r["kind"] for r in (await client.get("/api/admin/activity-log?limit=50")).json()}
    assert {
        "settings.model_set", "settings.model_cleared",
        "settings.tag_base_set", "settings.tag_base_cleared",
        "settings.logo_set", "settings.logo_cleared",
    } <= kinds


@pytest.mark.parametrize(
    "base",
    [
        "http://headroom.local:8000/some/path",
        "http://headroom.local:8000/settings?tab=sharing",
        "http://headroom.local:8000/#frag",
        "http://headroom.local:8000?",
    ],
)
async def test_a_tag_host_is_only_a_host(client, base):
    """The tag path is APPENDED to this; anything after the host ends up in
    the middle of every label."""
    resp = await client.put("/api/settings/tags", json={"base_url": base})

    assert resp.status_code == 422, resp.text


async def test_a_trailing_slash_is_just_normalized(client):
    resp = await client.put("/api/settings/tags", json={"base_url": "http://headroom.local:8000/"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["base_url"] == "http://headroom.local:8000"
    assert resp.json()["example_url"] == "http://headroom.local:8000/t/h/1"


# ---- share links ------------------------------------------------------- #


async def test_a_share_label_is_cleaned_before_outsiders_see_it(client, anon_client):
    """The label is the title of the one page people outside the house see; a
    bidi override made it read as something else."""
    created = await client.post("/api/share-links", json={"label": "Brandon\u202e s hats\u0000"})
    assert created.status_code == 201, created.text

    public = (await anon_client.get(f"/api/public/share/{created.json()['token']}")).json()

    assert public["label"] == "Brandon s hats"


async def test_a_blank_share_label_is_refused(client):
    assert (await client.post("/api/share-links", json={"label": "   "})).status_code == 422
    assert (await client.post("/api/share-links", json={})).status_code == 201


# ---- bulk import ------------------------------------------------------- #


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize(
    "bad", [{"style": "not-a-style"}, {"size": "XXL"}, {"condition": "bogus"}],
    ids=["style", "size", "condition"],
)
async def test_import_defaults_are_validated_before_anything_is_spooled(client, monkeypatch, bad):
    """A bogus style was a 202, then every item failed in the worker.

    One bad field per case: sent together, any one field left as free text
    would still get a 422 from the other two, and nothing would notice.
    """
    from headroom.routes import _uploads

    spooled = []

    async def _spy(*args, **kwargs):
        spooled.append(args)
        return []

    monkeypatch.setattr(_uploads, "spool_batch", _spy)

    resp = await client.post(
        "/api/hats/import", files=[("photos", ("a.png", _png(), "image/png"))], data=bad
    )

    assert resp.status_code == 422, resp.text
    assert spooled == [], "the batch was spooled before its defaults were checked"


async def test_an_import_into_a_missing_or_full_case_is_refused_up_front(client):
    missing = await client.post(
        "/api/hats/import",
        files=[("photos", ("a.png", _png(), "image/png"))],
        data={"case_id": "99999"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Case not found"

    case = (await client.post("/api/cases", json={"case_type": "archive", "capacity": 1})).json()
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case["id"]},
    )
    full = await client.post(
        "/api/hats/import",
        files=[("photos", ("a.png", _png(), "image/png"))],
        data={"case_id": str(case["id"])},
    )
    assert full.status_code == 409


async def test_the_share_target_keeps_the_leading_files_over_the_total_cap(client, monkeypatch):
    """The share target's total cap could be deleted with the whole suite
    green. Lenient on purpose — a share sheet has no error page — so an
    over-total batch keeps what fits rather than failing."""
    from headroom.services import import_service

    one = len(_png())
    monkeypatch.setattr(import_service, "MAX_TOTAL_UPLOAD_BYTES", one * 2)

    resp = await client.post(
        "/share",
        files=[("photos", (f"{i}.png", _png(), "image/png")) for i in range(4)],
        follow_redirects=False,
    )

    assert resp.status_code == 303
    job_id = int(resp.headers["location"].split("job=")[1])
    job = (await client.get(f"/api/hats/import/{job_id}")).json()
    assert job["total"] == 2

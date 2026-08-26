"""Caddy's local CA must survive the card, and its replacement must be noticed.

An unclean shutdown on the deployment destroyed a key Caddy had written but
never fsynced, and HTTPS was broken for 37 days. The leaf certificate was never
the expensive part — Caddy reissues those. The ROOT is: every device that
browses the site installed it by hand through iOS Settings or macOS Keychain,
and a root is self-signed, so nothing can vouch for a replacement. Losing it
means visiting every device.

It lived only in Caddy's own volume and was in no backup this app takes.

The other half is detection. Caddy names every root
`Caddy Local Authority - <year> ECC Root`, so a regenerated authority is
indistinguishable by eye from the original — same name, same issuer, different
key — and the first symptom is a device reporting an invalid signature on a
chain that verifies perfectly at the server.
"""

from __future__ import annotations

import io
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from headroom.services import backup_service, ca_vault

pytestmark = pytest.mark.anyio


def _fake_pki(tmp_path: Path, monkeypatch, *, files=ca_vault.PKI_FILES) -> Path:
    """Stand in for the export sidecar's output directory."""
    pki = tmp_path / "pki"
    pki.mkdir()
    for name in files:
        (pki / name).write_text(f"-----BEGIN {name}-----\n")
    monkeypatch.setattr(ca_vault, "PKI_DIR", pki)
    return pki


# ---- what is on disk --------------------------------------------------- #


async def test_no_overlay_is_not_a_failure(tmp_path, monkeypatch):
    """Every deployment without LAN HTTPS has no CA, and that is normal."""
    monkeypatch.setattr(ca_vault, "PKI_DIR", tmp_path / "absent")

    assert ca_vault.exported_files() == []


async def test_all_four_files_are_found(tmp_path, monkeypatch):
    _fake_pki(tmp_path, monkeypatch)

    assert [p.name for p in ca_vault.exported_files()] == list(ca_vault.PKI_FILES)


async def test_a_partial_export_is_still_backed_up(tmp_path, monkeypatch):
    """The sidecar polls; a backup can land mid-copy.

    Half a CA is worth keeping — root.crt and root.key alone are enough to
    re-establish the authority every device already trusts.
    """
    _fake_pki(tmp_path, monkeypatch, files=("root.crt", "root.key"))

    assert [p.name for p in ca_vault.exported_files()] == ["root.crt", "root.key"]


async def test_the_file_list_is_explicit_not_globbed():
    """A future file in that directory must not silently enter backups.

    These are private keys; what gets copied off the box is an inspected
    decision, not whatever happens to be lying there.
    """
    assert ca_vault.PKI_FILES == (
        "root.crt", "root.key", "intermediate.crt", "intermediate.key",
    )


# ---- the backup -------------------------------------------------------- #


def _tar_names() -> list[str]:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        backup_service._add_ca_to_tar(tar)
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        return tar.getnames()


async def test_the_ca_lands_in_the_archive(tmp_path, monkeypatch):
    _fake_pki(tmp_path, monkeypatch)

    names = _tar_names()

    for f in ca_vault.PKI_FILES:
        assert f"data/caddy-pki/{f}" in names


async def test_the_archive_says_it_holds_private_keys(tmp_path, monkeypatch):
    """The tarball may be uploaded to a NAS or cloud by the post-backup hook.

    By then nothing else is around to mention that a trusted root's private
    key is inside it, so the warning has to travel with the file.
    """
    _fake_pki(tmp_path, monkeypatch)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        backup_service._add_ca_to_tar(tar)
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        note = tar.extractfile("data/caddy-pki/READ-ME-CA-KEYS.txt").read().decode()

    assert "PRIVATE KEYS" in note
    assert "HEADROOM_BACKUP_INCLUDE_CA=false" in note
    # Without this the reader has the key material and no idea what to do.
    assert "Restoring" in note


async def test_opting_out_leaves_the_keys_behind(tmp_path, monkeypatch):
    """A trusted root's key is a broader capability than the rest of the DB."""
    _fake_pki(tmp_path, monkeypatch)
    monkeypatch.setenv("HEADROOM_BACKUP_INCLUDE_CA", "false")

    assert _tar_names() == []


async def test_no_ca_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ca_vault, "PKI_DIR", tmp_path / "absent")

    assert _tar_names() == []


async def test_an_unreadable_ca_never_breaks_the_backup(tmp_path, monkeypatch):
    """A partial backup beats a failed one, always."""
    def _boom():
        raise OSError("mount went away")

    monkeypatch.setattr(ca_vault, "exported_files", _boom)

    assert _tar_names() == []   # swallowed, no exception


async def test_the_ca_is_part_of_what_triggers_a_backup(tmp_path, monkeypatch):
    """Backups are change-gated, so a new CA must count as a change.

    Otherwise the archive holding the OLD root ages out of the retention
    window while the new one is never captured — losing both.
    """
    pki = _fake_pki(tmp_path, monkeypatch)
    monkeypatch.setattr(backup_service, "_db_path", lambda: None)
    monkeypatch.setattr(backup_service.settings, "upload_dir", tmp_path / "nope")

    before = backup_service._data_fingerprint_sync()
    (pki / "root.crt").write_text("-----BEGIN a completely different root-----\n")
    after = backup_service._data_fingerprint_sync()

    assert before != after


# ---- noticing a replaced root ------------------------------------------ #


async def test_first_sighting_is_recorded_not_alarmed(db_session):
    changed, expected = await ca_vault.check_root(db_session, "AA:BB")

    assert changed is False
    assert expected == "AA:BB"


async def test_the_same_root_stays_quiet(db_session):
    await ca_vault.check_root(db_session, "AA:BB")

    changed, expected = await ca_vault.check_root(db_session, "AA:BB")

    assert changed is False
    assert expected == "AA:BB"


async def test_a_replaced_root_is_reported(db_session):
    """The event that silently breaks every device on the network."""
    await ca_vault.check_root(db_session, "AA:BB")

    changed, expected = await ca_vault.check_root(db_session, "CC:DD")

    assert changed is True
    # What the DEVICES trust — the actionable half. Caddy gives both roots the
    # same name, so the fingerprints are the only thing telling them apart.
    assert expected == "AA:BB"


async def test_the_alarm_does_not_reset_itself(db_session):
    """A mismatch must keep reporting until somebody deals with it.

    Overwriting the stored fingerprint on mismatch would silence the alarm on
    the very next poll, roughly a minute later, and the devices would still be
    broken.
    """
    await ca_vault.check_root(db_session, "AA:BB")
    await ca_vault.check_root(db_session, "CC:DD")

    changed, expected = await ca_vault.check_root(db_session, "CC:DD")

    assert changed is True
    assert expected == "AA:BB"


async def test_no_certificate_at_all_is_not_a_change(db_session):
    """Deployments without the overlay must not report a CA problem."""
    changed, expected = await ca_vault.check_root(db_session, None)

    assert changed is False
    assert expected is None


# ---- a leaf cut short by its issuer ------------------------------------ #


def _cert(tmp_path, monkeypatch, *, not_after):
    """Write an intermediate.crt expiring at `not_after` into the fake PKI."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    pki = tmp_path / "pki"
    pki.mkdir(exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Caddy Intermediate")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_after - timedelta(days=7))
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    (pki / "intermediate.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(ca_vault, "PKI_DIR", pki)
    return not_after


async def test_a_leaf_matching_its_issuers_expiry_is_clamped(tmp_path, monkeypatch):
    """Caddy issues both in one operation, so a clamp matches to the second.

    The real case: 820 days requested, ~6 granted, because the intermediate
    had 6 days left. Renewing produces another 6-day certificate.
    """
    expiry = _cert(tmp_path, monkeypatch, not_after=datetime(2026, 8, 30, 5, 31, 42, tzinfo=timezone.utc))

    assert ca_vault.clamped_by_issuer(expiry) is True


async def test_a_leaf_expiring_on_its_own_schedule_is_not_clamped(tmp_path, monkeypatch):
    """An ordinary short cert under a healthy issuer. Different fix entirely."""
    _cert(tmp_path, monkeypatch, not_after=datetime(2034, 11, 12, tzinfo=timezone.utc))

    leaf = datetime(2026, 8, 30, 5, 31, 42, tzinfo=timezone.utc)
    assert ca_vault.clamped_by_issuer(leaf) is False


async def test_no_intermediate_means_no_claim_either_way(tmp_path, monkeypatch):
    monkeypatch.setattr(ca_vault, "PKI_DIR", tmp_path / "absent")

    assert ca_vault.issuer_expiry() is None
    assert ca_vault.clamped_by_issuer(datetime.now(timezone.utc)) is False


async def test_an_unreadable_intermediate_never_breaks_the_page(tmp_path, monkeypatch):
    """This runs inside the settings endpoint; a diagnostic must not 500 it."""
    pki = tmp_path / "pki"
    pki.mkdir()
    (pki / "intermediate.crt").write_text("not a certificate")
    monkeypatch.setattr(ca_vault, "PKI_DIR", pki)

    assert ca_vault.issuer_expiry() is None

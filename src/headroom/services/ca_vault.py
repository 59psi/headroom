"""Caddy's local CA: keeping it, and noticing when it changes.

This exists because of a real 37-day outage. An unclean shutdown on the
deployment destroyed a key Caddy had written but never fsynced; renewal then
queued every ten minutes and never completed, and the site served an expired
certificate for over a month while every other signal stayed green.

The certificate itself was recoverable — Caddy simply reissues one. What is
**not** recoverable is the ROOT of the local CA. Every device that reaches
`https://headroom.local` has installed that root by hand, through iOS Settings
or macOS Keychain, and a root is self-signed: there is no authority above it to
vouch for a replacement. Lose it and the only repair is walking to every phone,
tablet and laptop and installing a new one. That is the loss this module is
about, and it is a different order of problem from a missing leaf.

Three gaps, and only two of them are ours to close:

**Backup.** Caddy's PKI lives in its own volume and was never part of any
backup this app takes. `_data_fingerprint_sync` measured the database and the
uploads tree; a card failure took the CA with it. The export sidecar now copies
the whole authority — including the private keys — where this process can read
it, and `backup_service` folds it into the archive.

**Verification.** Nothing noticed when the served root changed. Caddy names
every root `Caddy Local Authority - <year> ECC Root`, so a regenerated CA is
indistinguishable by eye from the original: same name, same issuer string,
completely different key. The first symptom is a device reporting an invalid
signature on a chain that verifies perfectly at the server. `check_root()`
records the fingerprint the first time it sees one and reports a mismatch
forever after, so the event is caught the hour it happens instead of the day
somebody complains.

**Durability.** Not ours. Caddy decides when to fsync its own files and this
app cannot reach inside it. What is here is a durable *copy*, which is why the
backup half matters more than it looks: it is the only mitigation available.

Private keys are involved, so the tradeoff is stated rather than assumed. A
backup that contains this root key is a bigger prize than one that does not:
the database holds credentials for this app, where a trusted root can sign a
certificate for *any* host that the trusting devices will believe. It is
included by default because the failure it prevents is the one that actually
happened here, and because backing up its data directory is Caddy's own
guidance — but `HEADROOM_BACKUP_INCLUDE_CA=false` turns it off for anyone whose
backups travel somewhere they would rather that key did not.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import env_flag

logger = logging.getLogger(__name__)

#: Where the export sidecar publishes the full authority, mode 0600 and owned
#: by this container's uid. A sibling of the world-readable `root.crt` that
#: `routes/ca_cert` serves, and deliberately a separate directory: that file is
#: handed to anyone who asks and these must never be.
PKI_DIR = Path("/caddy-ca/pki")

#: The four files Caddy keeps for a local authority. Named explicitly rather
#: than globbed so that a future addition to that directory is an inspected
#: decision instead of something a backup silently starts carrying.
PKI_FILES = ("root.crt", "root.key", "intermediate.crt", "intermediate.key")

#: `app_settings` key holding the SHA-256 of the root this install has been
#: handing out. Written once, on first sight, and compared thereafter.
ROOT_FINGERPRINT_KEY = "ca_root_sha256"

#: Included in the archive beside the keys. A tarball that carries a private
#: key should say so in a file that travels with it — a note in the changelog
#: does not survive being copied to a NAS.
BACKUP_README = """\
This archive contains Caddy's LOCAL CERTIFICATE AUTHORITY, including its
PRIVATE KEYS (caddy-pki/root.key, caddy-pki/intermediate.key).

Why it is here
--------------
Every device that browses to this app over HTTPS on the LAN has installed
caddy-pki/root.crt as a trusted root, by hand. A root certificate is
self-signed, so nothing can vouch for a replacement: if this authority is
lost, the only repair is installing a new root on every device again.

Treat this archive accordingly
------------------------------
Anyone holding root.key can mint a certificate for ANY hostname that those
devices will trust -- not just this app. That is a broader capability than
anything else in this backup. Keep it where you would keep a password vault.

Set HEADROOM_BACKUP_INCLUDE_CA=false to leave the CA out of future backups.
You will still get the database and photos; you will re-trust every device if
the card dies.

Restoring
---------
Stop the stack, then copy the four files back into Caddy's volume and let it
start:

    docker compose down
    docker run --rm -v headroom_caddy-data:/data -v "$PWD/caddy-pki":/restore \\
      alpine sh -c 'mkdir -p /data/caddy/pki/authorities/local &&
                    cp /restore/* /data/caddy/pki/authorities/local/ &&
                    chown -R root:root /data/caddy/pki &&
                    chmod 0700 /data/caddy/pki/authorities/local'
    docker compose -f docker-compose.yml -f docker-compose.https-lan.yml up -d

Check afterwards that Settings shows the same CA fingerprint your devices
already trust. If it differs, Caddy generated a fresh authority and the
devices need the new root.
"""


def include_in_backup() -> bool:
    """Whether the CA travels with the backup. Read live, not at import.

    Same pattern as the other runtime toggles: an operator changing their mind
    should not need a rebuild, and tests need to flip it per case.
    """
    return env_flag("HEADROOM_BACKUP_INCLUDE_CA", default=True)


def exported_files() -> list[Path]:
    """The PKI files actually present, in a stable order.

    Empty on every deployment without the LAN-HTTPS overlay, which is the
    normal case and not a problem — the caller must treat it as "nothing to
    back up" rather than as a failure.
    """
    found = []
    for name in PKI_FILES:
        path = PKI_DIR / name
        try:
            if path.is_file():
                found.append(path)
        except OSError:
            # An unreadable mount reads as absent. The CA-certificate route
            # learned this the hard way: `is_file()` reports a permission
            # failure as plain False, so the two must never be conflated
            # silently. Log it and carry on -- a backup that skips the CA is
            # far better than one that raises.
            logger.warning("Could not stat CA file %s", path, exc_info=True)
    return found


def fingerprint_parts() -> list[str]:
    """Size+mtime signature of the CA, for the backup change-detector.

    Without this a regenerated authority would not by itself trigger a new
    backup, so the archive holding the OLD root could age out of the retention
    window while the new one was never captured — losing both.
    """
    parts = []
    for name in PKI_FILES:
        path = PKI_DIR / name
        try:
            st = path.stat()
            parts.append(f"ca/{name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append(f"ca/{name}:-")
    return parts


#: A leaf whose expiry lands this close to its issuer's was CLAMPED to it
#: rather than given its configured lifetime. Caddy issues both in the same
#: operation, so the two timestamps match to the second when clamping happens;
#: a minute is slack for clock granularity, not a fuzzy match.
_CLAMP_TOLERANCE_SECONDS = 60


def issuer_expiry() -> datetime | None:
    """When the intermediate that signs our leaves runs out.

    Read from the exported PKI rather than the served chain: `getpeercert`
    returns the leaf alone, and the intermediate is sitting right here already.

    This exists because of a diagnosis that went wrong on the real deployment.
    Caddy was issuing SIX-DAY certificates against a configured 820, logging
    `cert lifetime would exceed issuer NotAfter, clamping lifetime` — the
    intermediate had a seven-day life and a leaf cannot outlive its issuer.
    The app correctly reported a certificate about to expire and then advised
    restarting Caddy, which would have reissued another six-day certificate.
    Naming the real cause is the difference between a fix and a loop.
    """
    path = PKI_DIR / "intermediate.crt"
    try:
        if not path.is_file():
            return None
        from cryptography import x509  # noqa: PLC0415 — heavy, only needed here

        return x509.load_pem_x509_certificate(path.read_bytes()).not_valid_after_utc
    except Exception:  # a diagnostic must never break the page
        logger.warning("Could not read intermediate expiry", exc_info=True)
        return None


def clamped_by_issuer(leaf_not_after: datetime | None) -> bool:
    """Is the leaf short because the INTERMEDIATE is nearly out, not itself?

    The two failures look identical on the certificate — a short validity
    window — and have opposite fixes. A genuinely expiring leaf is repaired by
    letting Caddy renew it. A clamped one is not repaired by renewal at all:
    every reissue lands on the same issuer ceiling until the intermediate is
    replaced.
    """
    issuer = issuer_expiry()
    if leaf_not_after is None or issuer is None:
        return False
    return abs((leaf_not_after - issuer).total_seconds()) <= _CLAMP_TOLERANCE_SECONDS


async def check_root(db: AsyncSession, current: str | None) -> tuple[bool, str | None]:
    """Has the root this install serves changed since we first saw it?

    Returns `(changed, expected)`. `changed` is True only when a fingerprint
    was recorded earlier AND differs from what is being served now — the case
    where every device on the network is about to start refusing the
    connection. A first sighting records and reports False; no sighting at all
    (no overlay) reports False.

    Deliberately never self-heals by overwriting the stored value on a
    mismatch. The stored fingerprint is what the DEVICES trust, and the whole
    value of the check is that it keeps saying so until somebody deals with it.
    """
    from headroom.services import settings_service  # noqa: PLC0415 — cycle

    if not current:
        return False, None

    expected = await settings_service.get_setting(db, ROOT_FINGERPRINT_KEY)
    if not expected:
        await settings_service.set_setting(db, ROOT_FINGERPRINT_KEY, current)
        await db.commit()
        logger.info("Recorded local CA root fingerprint %s", current)
        return False, current

    if expected != current:
        logger.error(
            "Local CA root CHANGED: devices trust %s but this install now serves "
            "%s. Every device must install the new root.",
            expected, current,
        )
        return True, expected

    return False, expected

"""Properties of the infra files that only a file scan can hold.

These are the shapes the adversarial review found by rendering compose and
reading the Dockerfile: an uv pin no updater could see, a QUIC port nothing
published, a build context that would ship the backup bundle, `/app` writable
by the runtime user.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.anyio


def _read(name: str) -> str:
    return (ROOT / name).read_text()


async def test_the_uv_pin_is_a_from_line_dependabot_can_see():
    dockerfile = _read("Dockerfile")
    assert "FROM ghcr.io/astral-sh/uv:" in dockerfile, (
        "the uv pin must be a FROM line — Dependabot's docker ecosystem parses "
        "those and ignores `COPY --from=ghcr.io/...:tag`"
    )
    assert "COPY --from=uv /uv" in dockerfile


async def test_the_runtime_stage_does_not_chown_app_to_the_runtime_user():
    dockerfile = _read("Dockerfile")
    assert "chown -R headroom:headroom /data /app" not in dockerfile, (
        "code the runtime user can rewrite survives every restart a compromise "
        "would need — /app is root-owned, only /data is the app's to write"
    )
    assert "COPY --from=python-base /app/src /app/src" in dockerfile, (
        "src must be copied WITHOUT --chown"
    )


async def test_the_image_declares_its_own_healthcheck():
    assert "HEALTHCHECK" in _read("Dockerfile"), (
        "`docker run` and CI get no healthcheck without one in the image"
    )


async def test_the_letsencrypt_overlay_publishes_udp_443_for_http3():
    overlay = _read("docker-compose.https.yml")
    assert '"443:443/udp"' in overlay, (
        "Caddy advertises h3 on UDP 443; without publishing it every fresh "
        "browser connection pays a QUIC timeout before falling back to h2"
    )


async def test_the_letsencrypt_overlay_sets_hsts():
    assert "Strict-Transport-Security" in _read("Caddyfile.https"), (
        "the app's middleware leaves HSTS to Caddy on the internet-facing overlay"
    )


async def test_both_caddyfiles_compress_the_bundle():
    assert "encode zstd gzip" in _read("Caddyfile")
    assert "encode zstd gzip" in _read("Caddyfile.https")


async def test_the_base_app_root_filesystem_is_read_only():
    compose = _read("docker-compose.yml")
    assert "read_only: true" in compose
    assert "stop_grace_period: 60s" in compose, (
        "the WAL checkpoint and four workers need longer than the 10 s default "
        "to shut down cleanly"
    )


@pytest.mark.parametrize("pattern", ["backups/", "*.pem", "*.key", "*.db-wal", "hardware"])
async def test_the_dockerignore_excludes_the_credential_bundle(pattern):
    assert pattern in _read(".dockerignore").splitlines(), (
        f"{pattern} is uploaded in the build context without this"
    )


@pytest.mark.parametrize("pattern", ["backups/", "*.pem", "*.key"])
async def test_the_gitignore_excludes_secrets_and_backups(pattern):
    assert pattern in _read(".gitignore").splitlines()


async def test_the_engines_floor_is_enforced_not_just_warned():
    npmrc = _read("frontend/.npmrc")
    assert "engine-strict=true" in npmrc, (
        "without this `npm ci` only WARNS on a too-old Node; setup.sh's comment "
        "claims it errors"
    )


async def test_both_manifests_declare_the_license():
    assert 'license = "AGPL-3.0-or-later"' in _read("pyproject.toml")
    assert '"license": "AGPL-3.0-or-later"' in _read("frontend/package.json")

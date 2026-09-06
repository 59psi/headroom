"""Every environment knob the code reads reaches the container.

Compose's `.env` feeds variable interpolation only — it never becomes the
container's environment — so a variable the docs say to "set in .env" does
nothing unless `docker-compose.yml` forwards it. At 2.77.3 the base file
forwarded three of some thirty: `HEADROOM_SETUP_TOKEN` in `.env` protected
nothing, silently, and `HEADROOM_MDNS_HOSTNAME=hats` reached Caddy (which
signs the certificate for `hats.local`) but not the app (which kept
advertising `headroom.local`). This enumerates what the code reads and checks
the compose file forwards it, with every exclusion written down and reasoned.

Forwarding as `${VAR:-}` means an unset knob arrives as an EMPTY string, so
the readers must treat empty as unset — the second half of this file.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
import yaml

from headroom import config

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parents[1]

#: Variables the code reads that the base compose file deliberately does NOT
#: forward. Each needs a reason; an entry without one is a gap wearing a label.
NOT_FORWARDED: dict[str, str] = {
    "HEADROOM_DATABASE_URL": "set by the image's ENV to the /data volume; a passthrough would let .env point the DB outside it",
    "HEADROOM_UPLOAD_DIR": "same — the image's ENV owns the volume layout",
    "HEADROOM_REMBG_MODEL": "deliberately unpinned: an `environment:` value beats the image ENV and would override the model baked in by the REMBG_MODEL build arg (see the comment in docker-compose.yml)",
    "HEADROOM_RP_ID": "computed by the HTTPS overlays from the hostname/domain; passkeys are per-origin",
    "HEADROOM_ORIGIN": "computed by the HTTPS overlays from the hostname/domain",
    "HEADROOM_MDNS_PORT": "set by each overlay to the port it actually serves (8000 / 80 / 443)",
    "HEADROOM_MELIN_CLIENT_ID": "melinrecap's public anonymous client id; overriding it is a code-level decision, not an operator knob",
    "HEADROOM_CORS_ORIGINS": "set explicitly in the base file",
    "HEADROOM_BACKUP_RSYNC_PASSWORD": "forwarded, under its own comment block",
    "HEADROOM_BACKUP_INCLUDE_CA": "forwarded, under its own comment block",
}


def _env_names_read_by_code() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "src" / "headroom").rglob("*.py"):
        names.update(re.findall(r"\"(HEADROOM_[A-Z0-9_]+)\"", path.read_text()))
    # pydantic-settings fields: prefix + upper-cased field name
    for field in config.Settings.model_fields:
        names.add(f"HEADROOM_{field.upper()}")
    return names


def _compose_env_keys() -> set[str]:
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    env = doc["services"]["headroom"]["environment"]
    return set(env.keys()) if isinstance(env, dict) else {e.split("=", 1)[0] for e in env}


async def test_every_env_knob_the_code_reads_is_forwarded_or_excused():
    read = _env_names_read_by_code()
    forwarded = _compose_env_keys()
    missing = sorted(n for n in read if n not in forwarded and n not in NOT_FORWARDED)
    assert missing == [], (
        "read by the code, forwarded by nothing, excused by nobody: "
        f"{missing} — add a `${{VAR:-}}` line to docker-compose.yml or a reasoned entry above"
    )
    stale = sorted(n for n in NOT_FORWARDED if n not in read)
    assert stale == [], f"excused but no longer read anywhere: {stale}"


async def test_an_empty_flag_means_unset_not_false(monkeypatch):
    """`${VAR:-}` arrives as "". The old reader tested `"" in ("1","true","yes")`
    and got False — which would have switched off mDNS, backups and both
    workers on every install whose `.env` did not opt in to each by name."""
    monkeypatch.setenv("HEADROOM_SOME_FLAG", "")
    assert config.env_flag("HEADROOM_SOME_FLAG", default=True) is True
    assert config.env_flag("HEADROOM_SOME_FLAG", default=False) is False
    monkeypatch.setenv("HEADROOM_SOME_FLAG", "false")
    assert config.env_flag("HEADROOM_SOME_FLAG", default=True) is False
    monkeypatch.setenv("HEADROOM_SOME_INT", "")
    assert config.env_int("HEADROOM_SOME_INT", 7) == 7
    monkeypatch.setenv("HEADROOM_SOME_FLOAT", "")
    assert config.env_float("HEADROOM_SOME_FLOAT", 2.5) == 2.5


async def test_an_empty_settings_field_keeps_its_default(monkeypatch):
    """pydantic-settings would otherwise take `HEADROOM_ANTHROPIC_MODEL=""` as
    the model NAME. `env_ignore_empty` makes the passthrough safe."""
    monkeypatch.setenv("HEADROOM_ANTHROPIC_MODEL", "")
    monkeypatch.setenv("HEADROOM_HTTP_TIMEOUT", "")
    fresh = config.Settings()
    assert fresh.anthropic_model == config.Settings.model_fields["anthropic_model"].default
    assert fresh.http_timeout == config.Settings.model_fields["http_timeout"].default


async def test_an_empty_or_bogus_log_level_does_not_stop_the_boot(monkeypatch):
    """`logging.basicConfig(level="")` raises — an outage for a blank line."""
    from headroom import app as app_module

    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        for value in ("", "verbose-ish"):
            for h in list(root.handlers):
                root.removeHandler(h)
            monkeypatch.setenv("HEADROOM_LOG_LEVEL", value)
            app_module._configure_logging()  # must not raise
            assert root.level == logging.INFO, value
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)

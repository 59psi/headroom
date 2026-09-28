"""`config.py`'s rule, executed: a bad knob is its default plus a warning.

Every one of these was a way a typo in `.env` did something worse than being
ignored: `HEADROOM_BACKUP_ENABLED=on` switched scheduled backups OFF;
`HEADROOM_HTTP_TIMEOUT=abc` and a non-JSON `HEADROOM_CORS_ORIGINS` stopped the
app from booting at import; `HEADROOM_HTTP_TIMEOUT=nan` was accepted and
crashed the event loop's selector on the first outbound request; a trailing
space in `HEADROOM_ORIGIN` failed every passkey ceremony while the TLS card,
reading the same variable its own way, reported it healthy.
"""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

from headroom import config

pytestmark = pytest.mark.anyio


# ---- env_flag ------------------------------------------------------------- #


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", "On", " on "])
async def test_every_true_spelling_is_true(monkeypatch, raw):
    monkeypatch.setenv("HEADROOM_PROBE_FLAG", raw)
    assert config.env_flag("HEADROOM_PROBE_FLAG", default=False) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "OFF"])
async def test_every_false_spelling_is_false(monkeypatch, raw):
    monkeypatch.setenv("HEADROOM_PROBE_FLAG", raw)
    assert config.env_flag("HEADROOM_PROBE_FLAG", default=True) is False


@pytest.mark.parametrize("raw", ["ture", "enabled", "Y", "2"])
@pytest.mark.parametrize("default", [True, False])
async def test_a_typo_is_the_default_and_says_so(monkeypatch, caplog, raw, default):
    """Not False. `HEADROOM_BACKUP_ENABLED=ture` meant "on"; reading it as
    off switched a data-protection feature off with nothing in the log."""
    monkeypatch.setenv("HEADROOM_PROBE_FLAG", raw)
    with caplog.at_level(logging.WARNING, logger="headroom.config"):
        assert config.env_flag("HEADROOM_PROBE_FLAG", default=default) is default
    assert any("HEADROOM_PROBE_FLAG" in r.getMessage() for r in caplog.records)


async def test_backups_stay_on_when_enabled_is_spelled_on(monkeypatch):
    from headroom.services import backup_service

    monkeypatch.setenv("HEADROOM_BACKUP_ENABLED", "on")
    assert backup_service.backup_enabled() is True


# ---- env_str / env_choice -------------------------------------------------- #


async def test_env_str_strips_and_treats_empty_as_unset(monkeypatch):
    monkeypatch.setenv("HEADROOM_PROBE_STR", "  value  ")
    assert config.env_str("HEADROOM_PROBE_STR") == "value"
    monkeypatch.setenv("HEADROOM_PROBE_STR", "   ")
    assert config.env_str("HEADROOM_PROBE_STR", "fallback") == "fallback"
    monkeypatch.delenv("HEADROOM_PROBE_STR")
    assert config.env_str("HEADROOM_PROBE_STR", "fallback") == "fallback"


async def test_env_choice_is_case_insensitive_and_closed(monkeypatch, caplog):
    monkeypatch.setenv("HEADROOM_PROBE_CHOICE", " normal ")
    assert config.env_choice("HEADROOM_PROBE_CHOICE", ("FULL", "NORMAL"), "FULL") == "NORMAL"
    monkeypatch.setenv("HEADROOM_PROBE_CHOICE", "sideways")
    with caplog.at_level(logging.WARNING, logger="headroom.config"):
        assert config.env_choice("HEADROOM_PROBE_CHOICE", ("FULL", "NORMAL"), "FULL") == "FULL"
    assert any("HEADROOM_PROBE_CHOICE" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("reader", "raw", "default"),
    [(config.env_int, "five", 5), (config.env_float, "abc", 2.5), (config.env_float, "nan", 2.5)],
)
async def test_numeric_knobs_say_when_they_ignore_a_value(monkeypatch, caplog, reader, raw, default):
    """They fell back correctly and silently; the rule is fallback AND a warning."""
    monkeypatch.setenv("HEADROOM_PROBE_NUM", raw)
    with caplog.at_level(logging.WARNING, logger="headroom.config"):
        assert reader("HEADROOM_PROBE_NUM", default) == default
    assert any("HEADROOM_PROBE_NUM" in r.getMessage() for r in caplog.records)


async def test_an_unset_knob_is_its_default_without_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("HEADROOM_PROBE_NUM", "")
    with caplog.at_level(logging.WARNING, logger="headroom.config"):
        assert config.env_int("HEADROOM_PROBE_NUM", 7) == 7
        assert config.env_float("HEADROOM_PROBE_NUM", 1.5) == 1.5
        assert config.env_flag("HEADROOM_PROBE_NUM", default=True) is True
    assert caplog.records == []


# ---- Settings --------------------------------------------------------------- #


@pytest.mark.parametrize("raw", ["abc", "nan", "inf", "-5", "0"])
async def test_a_bad_http_timeout_is_the_default(monkeypatch, caplog, raw):
    monkeypatch.setenv("HEADROOM_HTTP_TIMEOUT", raw)
    with caplog.at_level(logging.WARNING, logger="headroom.config"):
        assert config.Settings().http_timeout == 30.0
    assert any("HEADROOM_HTTP_TIMEOUT" in r.getMessage() for r in caplog.records)


async def test_a_real_http_timeout_is_read(monkeypatch):
    monkeypatch.setenv("HEADROOM_HTTP_TIMEOUT", "12.5")
    assert config.Settings().http_timeout == 12.5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.example", ["http://a.example"]),
        ("http://a.example, http://b.example", ["http://a.example", "http://b.example"]),
        ('["http://j.example", "http://k.example"]', ["http://j.example", "http://k.example"]),
    ],
)
async def test_cors_origins_take_a_list_either_way(monkeypatch, raw, expected):
    monkeypatch.setenv("HEADROOM_CORS_ORIGINS", raw)
    assert config.Settings().cors_origins == expected


async def test_malformed_cors_origins_are_the_default(monkeypatch):
    monkeypatch.setenv("HEADROOM_CORS_ORIGINS", '["http://unterminated')
    assert config.Settings().cors_origins == []


async def test_a_fallback_default_is_a_copy(monkeypatch):
    """Returning the class-level list would let one instance's mutation
    rewrite the default every later `Settings()` starts from. Pydantic's
    `FieldInfo.get_default` copies it; this pins that the fallback path
    relies on that and keeps doing so."""
    monkeypatch.setenv("HEADROOM_CORS_ORIGINS", "[broken")
    first = config.Settings()
    first.cors_origins.append("http://mutated.example")
    assert config.Settings().cors_origins == []


@pytest.mark.parametrize("raw", ["https://headroom.local ", " https://headroom.local/"])
async def test_the_origin_is_normalized_once_for_every_reader(monkeypatch, raw):
    monkeypatch.setenv("HEADROOM_ORIGIN", raw)
    monkeypatch.setenv("HEADROOM_RP_ID", " headroom.local ")
    s = config.Settings()
    assert s.origin == "https://headroom.local"
    assert s.rp_id == "headroom.local"


async def test_the_knobs_that_used_to_stop_the_boot_now_load():
    """In a fresh interpreter, because `settings = Settings()` runs at import —
    which is where the old failures happened (`uvicorn headroom.app:app`
    exited on the pydantic error before any handler existed). `config` and
    `database` are the modules that raised it; every API test already imports
    the rest of the app."""
    env = {
        "HEADROOM_HTTP_TIMEOUT": "abc",
        "HEADROOM_CORS_ORIGINS": "http://a.example",
        "HEADROOM_DATABASE_URL": "sqlite+aiosqlite:////nonexistent/boot-probe.db",
        "PATH": "/usr/bin:/bin",
    }
    result = subprocess.run(
        [sys.executable, "-c",
         "from headroom import database; from headroom.config import settings; "
         "print(settings.http_timeout, settings.cors_origins)"],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "30.0 ['http://a.example']" in result.stdout

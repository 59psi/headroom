"""Every `HEADROOM_*` knob, and the one rule they all follow.

Configuration is read two ways, and only two:

* **`Settings`** — frozen at import. Values the process is built around
  (the database URL, the upload directory, the passkey origin) that no code
  path should see change underneath it.
* **The `env_*` helpers** — read live at call time, so a test can flip a
  knob per-test with monkeypatch and a background loop picks up an edited
  value on its next tick.

A raw `os.environ.get("HEADROOM_...")` elsewhere is a third way, and it is
how `HEADROOM_ORIGIN` came to have two readers that disagreed: the TLS
health card stripped whitespace and passkeys did not, so the card could
check a different origin from the one sign-in verified against.

The rule both ways share: **a bad value degrades that one knob to its
default, with a warning, and never stops the boot.** A typo in `.env` that
takes the whole app down is worse than the knob it was meant to set.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
)
from pydantic_settings import BaseSettings, NoDecode

logger = logging.getLogger(__name__)

#: The spellings `env_flag` accepts. Both halves are explicit, because a flag
#: whose only rule is "one of these means True" reads every OTHER value as
#: False — and `HEADROOM_BACKUP_ENABLED=on` then switched scheduled backups
#: off, silently, while saying the opposite of what the operator wrote.
_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def env_str(name: str, default: str = "") -> str:
    """String env knob, stripped. Empty or unset is `default`.

    Stripped because a value pasted into `.env` with a trailing space is
    still the value the operator meant, and an unstripped copy is how two
    readers of one variable came to disagree.
    """
    raw = (os.environ.get(name) or "").strip()
    return raw or default


def env_raw(name: str, default: str = "") -> str:
    """String env knob EXACTLY as set — not stripped. Empty or unset is `default`.

    For the one kind of value this app must judge rather than repair: one
    something ELSE also reads verbatim. `HEADROOM_MDNS_HOSTNAME` is appended to
    `.local` by the LAN-HTTPS overlay for Caddy's site address, the origin and
    the passkey RP id, so `"  lids  "` or `"Hats"` has to be seen as written
    and refused (`mdns_service.hostname_problem`) — a copy this module quietly
    cleaned up would advertise a name the certificate does not carry.
    """
    raw = os.environ.get(name) or ""
    return raw or default


def env_flag(name: str, default: bool = True) -> bool:
    """Boolean env toggle: 1/true/yes/on or 0/false/no/off, case-insensitive.

    Read live at call time — unlike Settings, which is frozen at import — so
    tests can flip feature flags per-test via monkeypatch.

    Anything else is a typo, and a typo is the default plus a warning: the
    same trade `env_float` and `env_choice` make. Returning False for it, as
    this did, is not "off" — it is a data-protection feature switching off
    because someone spelled "true" as "ture", with nothing in the log.
    """
    raw = env_str(name)
    if not raw:
        # Empty means UNSET, not false. `docker-compose.yml` forwards every
        # operator knob as `${VAR:-}` — an empty string when `.env` does not
        # set it — and the old `"" in ("1", "true", "yes")` read that as False,
        # which would have switched off mDNS, backups and both workers on every
        # install that had not opted in to each by name.
        return default
    word = raw.lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    return _ignored(
        name, raw,
        f"not one of {'/'.join(sorted(_TRUE_WORDS))} or {'/'.join(sorted(_FALSE_WORDS))}",
        default,
    )


def env_choice(name: str, choices: tuple[str, ...], default: str) -> str:
    """One of a closed set of UPPERCASE words, case-insensitive; else `default`.

    For values that are interpolated somewhere a bound parameter cannot go (a
    PRAGMA) or that select a mode: anything outside `choices` is discarded
    with a warning rather than passed through.
    """
    raw = env_str(name).upper()
    if raw in choices:
        return raw
    if raw:
        return _ignored(name, raw, f"not one of {', '.join(choices)}", default)
    return default


def env_float(name: str, default: float) -> float:
    """Numeric env tunable, falling back to `default` when unset or unparseable.

    Same live-read/monkeypatchable contract as `env_flag`, and the same
    degrade-don't-crash trade the services rely on: a typo'd value turns that
    one knob back to its default instead of failing app startup.
    """
    raw = env_str(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return _ignored(name, raw, "not a number", default)
    # `float("nan")` and `float("inf")` parse. `HEADROOM_REPRICING_INTERVAL_
    # HOURS=nan` reached `asyncio.sleep(nan)` — "Invalid delay: NaN", raised
    # outside the loop's try, and the scheduler task was dead for the life of
    # the process with one failure recorded; `inf` did the same one
    # OverflowError later. A knob that is not a number is a typo, and a typo
    # turns the knob back to its default like every other unparseable value.
    if not math.isfinite(value):
        return _ignored(name, raw, "not a finite number", default)
    return value


def env_int(name: str, default: int) -> int:
    """Integer counterpart to `env_float`."""
    raw = env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return _ignored(name, raw, "not a whole number", default)


def _ignored[T](name: str, raw: str, why: str, default: T) -> T:
    """Say which knob was ignored and why, and hand back its default.

    Every helper above degrades through here, so "a bad value is the default
    plus a warning" is one behavior rather than four spellings of it (two of
    which used to return the default in silence).
    """
    logger.warning("Ignoring %s=%r — %s; using %r", name, raw, why, default)
    return default


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./headroom.db"
    upload_dir: Path = Path("uploads")
    # `NoDecode`: pydantic-settings JSON-decodes a `list` field straight out of
    # the environment, BEFORE any validator runs — so the natural spelling,
    # `HEADROOM_CORS_ORIGINS=http://a.example`, raised `SettingsError` at
    # import and the app never booted. `_parse_origins` below takes a JSON
    # list or a comma-separated string instead.
    #
    # Empty by default, because CORS is opt-in: `app.create_app` installs
    # CORSMiddleware only when this list is non-empty. The SPA is same-origin
    # everywhere it runs — served by this app in production, and behind Vite's
    # `/api` + `/uploads` proxy in development — so it never needs CORS. The old
    # default, the Vite dev server's `http://localhost:5173`, made the "opt-in"
    # comment in `create_app` false on every install: the middleware was always
    # on, granting credentialed reads to an origin nothing in the project uses.
    cors_origins: Annotated[list[str], NoDecode] = []

    # Claude API key fallback — UI-stored key in DB takes precedence.
    anthropic_api_key: str | None = None

    # Google Cloud Vision API key (fallback brand detection when Claude is
    # unavailable). Same precedence rule: UI-stored key in DB wins.
    google_vision_api_key: str | None = None

    # eBay Browse API keyset (HEADROOM_EBAY_APP_ID / HEADROOM_EBAY_CERT_ID),
    # for ops users who inject it through docker-compose. The keyset stored
    # in Settings wins, like the keys above: `ebay_service` resolves both
    # halves through `settings_service.get_key`, which reads THESE fields as
    # its environment fallback — without them the env keyset resolved to None.
    ebay_app_id: str | None = None
    ebay_cert_id: str | None = None

    # melinrecap.com is a Treet marketplace on Sharetribe Flex; this is the
    # public (anonymous, public-read) client id its own frontend embeds in
    # the JS bundle. Override via env if Treet ever rotates it.
    melin_client_id: str = "89cea352-482e-4f00-a2c1-5bf3d5036e7b"

    # Default Claude vision model. Sonnet is the balanced tier and the right
    # default for one-image-in / one-tool-call-out analysis; Sonnet 5 is both
    # newer and cheaper than the 4.6 it replaced. Every current Claude model
    # accepts image input, so any of them works here — the Settings UI lists
    # the useful ones. Override with HEADROOM_ANTHROPIC_MODEL, or use
    # POST /api/settings/api-key/test to verify a model id + key end-to-end.
    anthropic_model: str = "claude-sonnet-5"

    # Per-request timeout (seconds) for outbound HTTP (Claude / Melin Recap).
    # Positive and finite — see `_positive_finite`.
    http_timeout: float = 30.0

    # WebAuthn (passkeys) relying-party identity. rp_id must equal the domain
    # the app is served on; origin the full scheme://host[:port]. Browsers
    # require a secure context (HTTPS or localhost) to offer passkeys.
    # Normalized by `_normalize_identity`; `tls_health` reads this same value.
    rp_id: str = "localhost"
    origin: str = "http://localhost:8000"

    # Where the TLS watch CONNECTS to read the served certificate; the origin's
    # hostname is still what it asks for (SNI) and checks the certificate
    # against. Unset, it connects to that hostname. The LAN-HTTPS overlay sets
    # 127.0.0.1: its hostname is a `.local` mDNS name the container cannot
    # resolve (no mDNS resolver inside the image), so the watch failed every
    # day with "Name or service not known" while Caddy was answering on the
    # same host network all along.
    tls_probe_address: str | None = None

    # Retired: HEADROOM_ADMIN_TOKEN. Real accounts replaced the optional
    # bearer guard in v1.0; the env var is ignored if still set.

    # `env_ignore_empty`: the compose passthroughs forward unset knobs as empty
    # strings, and without this pydantic-settings would take `HEADROOM_ANTHROPIC_
    # MODEL=""` as the model name rather than falling through to the default.
    model_config = {"env_prefix": "HEADROOM_", "env_ignore_empty": True}

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: Any) -> Any:
        """A JSON list (the documented form) or `a, b` (the natural one)."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]

    @field_validator("http_timeout")
    @classmethod
    def _positive_finite(cls, value: float) -> float:
        # `nan` and `-5` both parse as floats, and both were accepted. An
        # httpx client built with `timeout=nan` then crashed the asyncio
        # selector itself (`timeout argument must be a number`), and a
        # negative one times out every request before it is sent.
        if not math.isfinite(value) or value <= 0:
            raise ValueError("must be a positive, finite number of seconds")
        return value

    @field_validator("origin", "rp_id")
    @classmethod
    def _normalize_identity(cls, value: str) -> str:
        # WebAuthn compares the browser's origin to this string exactly, and a
        # browser's origin never ends in "/" or carries a space. A trailing
        # space pasted into `.env` failed every passkey ceremony while the TLS
        # card (which stripped) reported the same origin healthy.
        return value.strip().rstrip("/")

    # Declared LAST on purpose: pydantic runs wrap validators outermost in
    # reverse definition order, so this one wraps every field's parsing AND
    # the field validators above — a `ValueError` from any of them lands here.
    @field_validator("*", mode="wrap")
    @classmethod
    def _degrade_to_default(
        cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> Any:
        """The module rule, enforced for every field rather than listed per field.

        Only an ENVIRONMENT value can reach this (defaults are not validated),
        so falling back is always "ignore what the operator typed". The value
        itself is not logged: this class also holds API keys.
        """
        try:
            return handler(value)
        except (ValidationError, ValueError) as exc:
            reason = (
                exc.errors()[0]["msg"] if isinstance(exc, ValidationError) and exc.errors()
                else str(exc)
            )
            # `get_default` hands back a copy of a mutable default (pydantic
            # deep-copies it, as for an ordinary default), so one instance
            # mutating its fallback `cors_origins` cannot rewrite the next's.
            field = cls.model_fields[info.field_name]
            default = field.get_default(call_default_factory=True)
            logger.warning(
                "Ignoring HEADROOM_%s — %s; using the default (%r)",
                info.field_name.upper(), reason, default,
            )
            return default


settings = Settings()

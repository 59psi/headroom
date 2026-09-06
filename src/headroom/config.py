import os
from pathlib import Path

from pydantic_settings import BaseSettings


def env_flag(name: str, default: bool = True) -> bool:
    """Truthy env toggle ("1"/"true"/"yes", case-insensitive).

    Read live at call time — unlike Settings, which is frozen at import — so
    tests can flip feature flags per-test via monkeypatch.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        # Empty means UNSET, not false. `docker-compose.yml` forwards every
        # operator knob as `${VAR:-}` — an empty string when `.env` does not
        # set it — and the old `"" in ("1", "true", "yes")` read that as False,
        # which would have switched off mDNS, backups and both workers on every
        # install that had not opted in to each by name.
        return default
    return raw.lower() in ("1", "true", "yes")


def env_float(name: str, default: float) -> float:
    """Numeric env tunable, falling back to `default` when unset or unparseable.

    Same live-read/monkeypatchable contract as `env_flag`, and the same
    degrade-don't-crash trade the services rely on: a typo'd value turns that
    one knob back to its default instead of failing app startup.
    """
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_int(name: str, default: int) -> int:
    """Integer counterpart to `env_float`."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./headroom.db"
    upload_dir: Path = Path("uploads")
    cors_origins: list[str] = ["http://localhost:5173"]

    # Claude API key fallback — UI-stored key in DB takes precedence.
    anthropic_api_key: str | None = None

    # Google Cloud Vision API key (fallback brand detection when Claude is
    # unavailable). Same precedence rule: UI-stored key in DB wins.
    google_vision_api_key: str | None = None

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
    http_timeout: float = 30.0

    # WebAuthn (passkeys) relying-party identity. rp_id must equal the domain
    # the app is served on; origin the full scheme://host[:port]. Browsers
    # require a secure context (HTTPS or localhost) to offer passkeys.
    rp_id: str = "localhost"
    origin: str = "http://localhost:8000"

    # Retired: HEADROOM_ADMIN_TOKEN. Real accounts replaced the optional
    # bearer guard in v1.0; the env var is ignored if still set.

    # `env_ignore_empty`: the compose passthroughs forward unset knobs as empty
    # strings, and without this pydantic-settings would take `HEADROOM_ANTHROPIC_
    # MODEL=""` as the model name rather than falling through to the default.
    model_config = {"env_prefix": "HEADROOM_", "env_ignore_empty": True}


settings = Settings()

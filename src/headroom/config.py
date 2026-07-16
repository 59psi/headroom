import os
from pathlib import Path

from pydantic_settings import BaseSettings


def env_flag(name: str, default: bool = True) -> bool:
    """Truthy env toggle ("1"/"true"/"yes", case-insensitive).

    Read live at call time — unlike Settings, which is frozen at import — so
    tests can flip feature flags per-test via monkeypatch.
    """
    raw = os.environ.get(name, "true" if default else "false")
    return raw.lower() in ("1", "true", "yes")


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

    # Default Claude vision model. `claude-sonnet-4-6` is a current Anthropic
    # Sonnet id (Claude 4.6 family). Override with HEADROOM_ANTHROPIC_MODEL if
    # you want a different model, or use POST /api/settings/api-key/test in
    # the UI to verify the configured model + key actually work end-to-end.
    anthropic_model: str = "claude-sonnet-4-6"

    # Per-request timeout (seconds) for outbound HTTP (Claude / Melin Recap).
    http_timeout: float = 30.0

    # WebAuthn (passkeys) relying-party identity. rp_id must equal the domain
    # the app is served on; origin the full scheme://host[:port]. Browsers
    # require a secure context (HTTPS or localhost) to offer passkeys.
    rp_id: str = "localhost"
    origin: str = "http://localhost:8000"

    # Retired: HEADROOM_ADMIN_TOKEN. Real accounts replaced the optional
    # bearer guard in v1.0; the env var is ignored if still set.

    model_config = {"env_prefix": "HEADROOM_"}


settings = Settings()

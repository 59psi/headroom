from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./headroom.db"
    upload_dir: Path = Path("uploads")
    cors_origins: list[str] = ["http://localhost:5173"]

    # Claude API key fallback — UI-stored key in DB takes precedence.
    anthropic_api_key: str | None = None

    # Default Claude vision model. `claude-sonnet-4-6` is a current Anthropic
    # Sonnet id (Claude 4.6 family). Override with HEADROOM_ANTHROPIC_MODEL if
    # you want a different model, or use POST /api/settings/api-key/test in
    # the UI to verify the configured model + key actually work end-to-end.
    anthropic_model: str = "claude-sonnet-4-6"

    # Per-request timeout (seconds) for outbound HTTP (Claude / Melin Recap).
    http_timeout: float = 30.0

    # Optional shared secret for /api/settings/api-key (set/delete/test) routes.
    # Unset → endpoints are open (current single-user-on-LAN behaviour, with
    # a startup warning logged). Set → requests must include
    # `Authorization: Bearer <token>`.
    admin_token: str | None = None

    model_config = {"env_prefix": "HEADROOM_"}


settings = Settings()

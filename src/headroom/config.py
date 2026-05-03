from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./headroom.db"
    upload_dir: Path = Path("uploads")
    cors_origins: list[str] = ["http://localhost:5173"]

    # Claude API key fallback — UI-stored key in DB takes precedence.
    anthropic_api_key: str | None = None

    # Claude vision model used for hat analysis.
    anthropic_model: str = "claude-sonnet-4-6"

    # Per-request timeout (seconds) for outbound HTTP (Claude / Melin Recap).
    http_timeout: float = 30.0

    model_config = {"env_prefix": "HEADROOM_"}


settings = Settings()

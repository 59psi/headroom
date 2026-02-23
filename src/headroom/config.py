from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./headroom.db"
    upload_dir: Path = Path("uploads")
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_prefix": "HEADROOM_"}


settings = Settings()

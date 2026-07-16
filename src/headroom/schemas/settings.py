from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyStatus(BaseModel):
    """Public-facing view of the Anthropic API key — never the raw value."""

    configured: bool
    source: str | None = None  # "database" | "environment" | None
    masked: str | None = None  # e.g. "sk-a...xyz1"


class ApiKeyUpdate(BaseModel):
    api_key: str = Field(min_length=8, max_length=200)


class ApiKeyTestResult(BaseModel):
    ok: bool
    detail: str


class ModelStatus(BaseModel):
    """Active Claude model id + where it came from."""

    # `model_` prefix is reserved by pydantic — opt out so the natural name works.
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    source: str  # "database" | "environment" | "default"


class ModelUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str = Field(min_length=3, max_length=120)


class MdnsStatus(BaseModel):
    """Read-only LAN discovery state — configured via HEADROOM_MDNS_* env only."""

    enabled: bool
    advertising: bool
    hostname: str  # e.g. "headroom.local"
    port: int
    ip: str | None = None
    url: str | None = None
    error: str | None = None


class RecentError(BaseModel):
    hat_id: int
    display_id: str | None
    analysis_error: str | None
    analyzed_at: datetime | None
    photo_path: str | None


class BackupInfo(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime

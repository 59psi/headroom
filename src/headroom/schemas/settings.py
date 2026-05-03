from pydantic import BaseModel, Field


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

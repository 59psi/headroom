from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class TagBaseStatus(BaseModel):
    """The host burned into printed QR labels and NFC tags."""

    base_url: str
    source: str  # "settings" | "request"
    #: A worked example at the current base, so the UI can show what will
    #: actually be written rather than asking the reader to assemble it.
    example_url: str


class TagBaseUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=200)

    @field_validator("base_url")
    @classmethod
    def _must_carry_a_scheme(cls, v: str) -> str:
        """A bare host is not a usable tag.

        Both destinations need an absolute URL with a scheme: an NFC NDEF URI
        record encodes one, and a QR without a scheme is read as plain text, so
        the camera offers to copy it instead of opening it. `headroom.local:8000`
        looks obviously right and silently produces tags that do nothing, which
        you'd discover only after sticking them to forty hats.
        """
        cleaned = v.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return cleaned

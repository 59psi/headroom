from datetime import datetime

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


class TlsStatusRead(BaseModel):
    """The certificate the HTTPS front door is actually serving.

    Read-only, and reported rather than enforced: an expired certificate
    belongs to Caddy, so failing readiness on it would restart-loop the app
    without fixing anything.
    """

    #: False on every deployment without an HTTPS front door, which is not a
    #: problem and must not be rendered as one.
    applicable: bool
    host: str | None = None
    port: int = 443
    not_before: datetime | None = None
    not_after: datetime | None = None
    days_remaining: float | None = None
    expired: bool = False
    #: Expired, or close enough that renewal has evidently stopped.
    needs_attention: bool = False
    #: A valid certificate for the wrong name fails in a browser just as hard.
    hostname_ok: bool | None = None
    #: True when the served root differs from the one recorded on first sight —
    #: i.e. Caddy regenerated the authority and every device that trusts the old
    #: root will now refuse the connection. Distinct from an expiry problem and
    #: far worse: reissuing a leaf is automatic, replacing a hand-installed root
    #: means visiting every device.
    ca_changed: bool = False
    #: The fingerprint the devices actually trust, when it differs from what is
    #: being served. Both are shown together or neither means anything — Caddy
    #: gives every root the same NAME, so only these tell them apart.
    ca_expected_sha256: str | None = None
    #: SHA-256 of the CA this install hands out. Published because Caddy names
    #: every root identically, so two installs yield two different roots with
    #: the same name — and only a fingerprint tells them apart.
    ca_sha256: str | None = None
    error: str | None = None


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


class GuestViewStatus(BaseModel):
    """Whether the collection is browsable without an account."""

    enabled: bool


class GuestViewUpdate(BaseModel):
    enabled: bool

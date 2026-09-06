from datetime import datetime

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiKeyStatus(BaseModel):
    """Public-facing view of an external API key (Anthropic, Google Vision) — never the raw value."""

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
    # The built-in default, so the picker can mark that option itself instead
    # of carrying "(default)" in a hand-typed label that a model bump left
    # pointing at a superseded id for a whole generation.
    default_model_id: str


class ModelUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    # It becomes the `model` parameter of every Claude call. Anthropic ids are
    # letters, digits, dots, dashes and colons; anything else (HTML, spaces)
    # is a typo at best and stored HTML at worst.
    model_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


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
    #: When the intermediate that signs our leaves runs out.
    issuer_not_after: datetime | None = None
    #: True when the served certificate is short because it was CLAMPED to a
    #: nearly-expired intermediate rather than because it is itself old. The
    #: two look identical on the certificate and have opposite fixes: renewal
    #: repairs the first and cannot repair the second, since every reissue
    #: lands on the same issuer ceiling until the intermediate is replaced.
    clamped_by_issuer: bool = False
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
    #: Global LAN IPv6, when the host has one. Advertised alongside the IPv4
    #: address — publishing v4 alone stalls every lookup for the client's full
    #: resolver timeout (see mdns_service's module docstring). None means the
    #: host has no global v6, not that it was withheld.
    ipv6: str | None = None
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
        # A scheme alone is not a host: `http://` was stored as `http:` and
        # every tag then read `http:/t/h/1`.
        parsed = urlsplit(cleaned)
        if not parsed.hostname:
            raise ValueError("must name a host, e.g. http://headroom.local:8000")
        if parsed.username or parsed.password:
            raise ValueError("must not carry credentials")
        return cleaned


class GuestViewStatus(BaseModel):
    """Whether the collection is browsable without an account."""

    enabled: bool


class GuestViewUpdate(BaseModel):
    enabled: bool


class LogoStatus(BaseModel):
    """Where the site logo is served from, or null when none is set.

    Was a hand-built `{"logo_path": ...}` dict in three route handlers — the
    shape CLAUDE.md's "no schema is declared inline in a route" exists to stop.
    """

    logo_path: str | None


class MetaOption(BaseModel):
    """One dropdown option: the stored value and the label a person reads."""

    value: str | int
    label: str


class StyleOption(MetaOption):
    """`is_beanie` is SERVED, not re-derived client-side: it decides which cases
    the picker offers, and a TypeScript copy of `BEANIE_STYLES` would be a
    second definition that disagrees the day a shape is added."""

    is_beanie: bool


class PaletteColor(BaseModel):
    name: str
    hex: str


class TextOption(BaseModel):
    """A free-text suggestion (colorways, model names) — `{value}` only."""

    value: str


class LivenessRead(BaseModel):
    status: str


class ReadinessCheck(BaseModel):
    """One readiness probe. `ok` is always present; everything else is the
    authenticated-caller detail (an anonymous caller — the Docker healthcheck —
    gets booleans only, so `path`, `error`, `free_bytes` etc. are absent)."""

    model_config = ConfigDict(extra="allow")

    ok: bool


class ReadinessRead(BaseModel):
    """`GET /health/ready`. The check NAMES differ by caller: anonymous callers
    get a collapsed `workers`, authenticated callers get `import_worker` and
    `analysis_worker` — hence a mapping rather than fixed attributes."""

    ok: bool
    checks: dict[str, ReadinessCheck]

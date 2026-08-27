"""I/O models for the `/api/admin` routes.

Mirrors `routes/admin/` — these were previously declared inline in the route
module, which put half the admin schemas here and half there.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class BackupHealthRead(BaseModel):
    """Whether the scheduler is working — which the file list cannot answer.

    A scheduler that died weeks ago and one that ran minutes ago produce an
    identical inventory; the newest file is the last success in both cases.
    """

    enabled: bool
    running: bool
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None

    last_success_derived: bool = False
    """True when `last_success_at` came from a file's mtime, not a recorded run.

    The health record is process-local and a restart clears it — and on a Pi
    with a restart policy, restarts are routine. Rather than report `null` and
    let it read as "never succeeded", the newest backup's mtime stands in, and
    this says which of the two you are looking at. Derived means a backup was
    written; it does NOT mean the scheduler is still alive to write another,
    which is what `running` is for.
    """

    last_error: str | None = None

    last_skip_reason: str | None = None
    """Why the last cycle wrote nothing, when that was the right answer.

    Backups are only written when the data has actually changed, so on a quiet
    collection the newest tarball can be legitimately old. Without this the UI
    could only show a stale timestamp and let the reader guess whether the
    scheduler had died.
    """

    consecutive_failures: int = 0


class BackupUploadProvider(BaseModel):
    """One transport, described well enough for the card to render it.

    The setup steps travel with the provider rather than living in the
    frontend, because they are facts about what the SERVER will run — the
    binary it needs, whether a secret comes from the host environment — and a
    second copy in TypeScript is a second thing to keep in step.
    """

    name: str
    label: str
    #: Shape of a valid destination, e.g. `user@host::module/path`.
    destination_hint: str
    example: str
    #: Host-side work the operator still has to do. "Configured" and "working"
    #: are different states, and everything between them is on this list.
    setup: list[str] = []
    #: Env var carrying the transport's secret, where it takes one. Named, not
    #: read: the value never leaves the host.
    secret_env: str | None = None
    binary: str
    binary_available: bool = False


class BackupUploadStatus(BaseModel):
    """Whether the off-box copy is configured, and whether it is working.

    Separate from `BackupHealthRead` because the two fail independently: a
    local backup can succeed every night while the upload has been failing for
    a month, and only the second means the archive exists nowhere but the SD
    card it is protecting against.
    """

    configured: bool
    provider: str | None = None
    destination: str | None = None
    #: True when the command comes from `HEADROOM_BACKUP_UPLOAD_CMD`. That
    #: variable wins over the stored setting and cannot be changed from here —
    #: it is settable only with host access, which is a privilege boundary the
    #: web UI must not be able to cross.
    from_environment: bool = False
    available_providers: list[BackupUploadProvider] = []
    #: Whether the CONFIGURED provider's binary exists in this container. None
    #: when nothing is configured. Published because none of these binaries are
    #: in the base image, and a missing one fails every unattended upload while
    #: the card would otherwise still read "configured".
    binary_available: bool | None = None
    #: These four survive a restart (persisted beside the backups). They answer
    #: "does a copy of my data exist off this card, and how old is it" — a fact
    #: about the world, not about this process. None here means genuinely never,
    #: not merely "not since the last restart".
    last_upload_at: datetime | None = None
    last_upload_ok: bool | None = None
    last_upload_error: str | None = None
    #: The archive the last attempt shipped. "It ran" is not actionable; the
    #: file and the timestamp are.
    last_upload_name: str | None = None
    upload_successes: int = 0
    upload_failures: int = 0


class BackupUploadUpdate(BaseModel):
    provider: str
    destination: str = Field(min_length=1, max_length=200)


class BackupUploadTestResult(BaseModel):
    ok: bool
    detail: str


class ActivityRow(BaseModel):
    id: int
    occurred_at: datetime
    kind: str
    entity_type: str
    entity_id: int | None
    summary: str
    details: str | None


class EbayCredsStatus(BaseModel):
    configured: bool
    app_id_masked: str | None = None
    marketplace: str = "EBAY_US"
    detected_env: str | None = None  # "production" | "sandbox" | "unknown"


class EbayCredsUpdate(BaseModel):
    app_id: str = Field(min_length=4, max_length=120)
    cert_id: str = Field(min_length=4, max_length=200)
    marketplace: str = "EBAY_US"


class PurchaseImport(BaseModel):
    items: list[dict]


class PendingHat(BaseModel):
    """One hat waiting on analysis, enough to render a row."""

    id: int
    display_id: str | None = None
    label: str | None = None
    photo_path: str | None = None
    # Set only while a hat is actually being worked on, which is what separates
    # the one in progress from the ones merely queued behind it.
    stage: str | None = None


class AnalysisJobRead(BaseModel):
    """A bulk re-analysis run. `done`/`failed` are derived, not stored."""

    id: int
    total: int
    done: int
    failed: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None


class AnalysisQueueStatus(BaseModel):
    """`queued` is the in-memory depth, `pending_count` what the DB says.

    They differ on purpose: the DB number survives a restart, so a non-empty
    `pending_count` alongside `worker_alive: false` is the signal that nothing
    is draining the queue.
    """

    worker_alive: bool
    queued: int
    pending_count: int
    pending: list[PendingHat] = []
    # The run in flight, if any, and a short history — enough to answer "did
    # the last one finish, and did anything fail?"
    current_job: AnalysisJobRead | None = None
    recent_jobs: list[AnalysisJobRead] = []


class ReanalyzeAllResult(BaseModel):
    queued: int
    worker_alive: bool
    job: AnalysisJobRead | None = None


class PurchaseRead(BaseModel):
    """A purchase-history line item.

    Was a hand-built dict in the route, so the one endpoint carrying prices had
    no declared shape.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_ref: str | None = None
    order_date: datetime | None = None
    item_title: str
    model_name: str | None = None
    colorway: str | None = None
    size: str | None = None
    price: float | None = None
    quantity: int | None = None
    hat_id: int | None = None
    source: str | None = None


class CatalogStatus(BaseModel):
    """The catalog's real size, for the Settings card."""

    entries: int
    models: int
    colorways: int
    last_harvest: str | None


class CatalogRefreshStarted(BaseModel):
    """202 body for the colorway harvest.

    The harvest walks up to 9 categories x 50 pages of an external API, which
    is minutes of sequential round-trips. It used to run inside the request, so
    the browser sat on an open connection long enough to hit any proxy timeout
    in front of it and the work was invisible while it ran. It now runs as a
    background task and this says so.
    """

    started: bool = True
    detail: str = "Catalog refresh running in the background — check back shortly."


class ConstructionAuditRow(BaseModel):
    """One construction value on record, and what depends on it."""

    construction: str
    hat_count: int
    #: Hats whose retail price came from the price table — i.e. derived from
    #: this construction rather than checked by a person.
    priced_from_table: int


class ConstructionClearResult(BaseModel):
    """What reassigning a construction did, or would do under `dry_run`."""

    construction: str
    #: What the matched hats become. None clears the field.
    to: str | None = None
    dry_run: bool
    hats_cleared: int
    #: Skipped because the audit log proves the owner typed this value.
    owner_set_skipped: int = 0
    model_names_corrected: int
    prices_cleared: int
    manual_prices_kept: int
    samples: list[str]


class FrozenPriceRow(BaseModel):
    """One hat whose price analysis can no longer touch."""

    hat_id: int
    display_id: str | None = None
    model_name: str | None = None
    resale_price: float | None = None
    estimated_new_price: float | None = None
    #: The hat carries marketplace provenance (a listing URL or a checked-at
    #: timestamp), so it WAS priced by the feed before something marked it
    #: manual. A hint that this one is the pre-2.57.0 bug rather than a person.
    was_market_priced: bool = False


class PriceReleaseResult(BaseModel):
    """What releasing frozen prices did, or would do under `dry_run`."""

    dry_run: bool
    released: int
    hats: list[FrozenPriceRow] = []


class AnalysisFailureGroup(BaseModel):
    """One distinct analysis failure, and how many hats it hit.

    Grouped rather than listed per hat: 235 hats failing for one reason is one
    problem, and a flat list of 235 identical rows hides that it is one.
    """

    #: The failure, trimmed to the part that identifies it.
    reason: str
    hat_count: int
    #: A few hat ids, so you can open one and see it for yourself.
    sample_hat_ids: list[int] = []
    #: Most recent time a hat hit this.
    last_seen: datetime | None = None
    #: True when the text looks like an Anthropic billing/quota refusal — the
    #: one failure that looks like a broken key but is not.
    is_billing: bool = False

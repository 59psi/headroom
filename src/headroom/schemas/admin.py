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
    last_error: str | None = None
    consecutive_failures: int = 0


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


class AnalysisJobRead(BaseModel):
    """A bulk re-analysis run. `done`/`failed` are derived, not stored."""

    id: int
    total: int
    done: int
    failed: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None


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

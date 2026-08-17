"""I/O models for the `/api/admin` routes.

Mirrors `routes/admin/` — these were previously declared inline in the route
module, which put half the admin schemas here and half there.
"""

from datetime import datetime

from pydantic import BaseModel, Field


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

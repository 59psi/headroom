"""I/O models for bulk import.

The route hand-built these dicts, which is how `bytes` — the per-item byte
count — ended up with no declared type on an endpoint the SPA polls every
couple of seconds while a job runs.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ImportJobItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    status: str
    hat_id: int | None = None
    error: str | None = None
    bytes: int | None = None


class ImportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    finished_at: datetime | None = None
    total: int
    done: int
    errors: int
    skipped: int
    status: str
    items: list[ImportJobItemRead] = []


class ImportJobCreated(BaseModel):
    """The 202 response — the SPA redirects to the job page with this id."""

    id: int
    total: int
    status: str

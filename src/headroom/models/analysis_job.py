from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from headroom.database import Base


class AnalysisJob(Base):
    """One bulk re-analysis run.

    Deliberately thin: it records what was asked for and when, and nothing
    about progress. Progress is *derived* by counting the hats tagged with this
    job id, because the analysis worker knows nothing about jobs and shouldn't
    have to — it drains hat ids. Storing counters here instead would mean the
    worker updating two places per hat, and a crash between them leaving a
    progress bar that permanently disagrees with reality.

    `total` is the exception: it is the size of the run at the moment it was
    queued, which cannot be recovered later if hats are deleted mid-run.
    """

    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    # 'running' until every tagged hat reaches a terminal analysis_status.
    status: Mapped[str] = mapped_column(String(20), default="running")

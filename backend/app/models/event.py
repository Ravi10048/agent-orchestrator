from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RunEvent(Base):
    """Append-only telemetry for live monitoring + persisted logs (LLD 06)."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(default=0, index=True)  # per-run monotonic order (LLD 09 reconnect/replay)
    type: Mapped[str] = mapped_column(String(30))  # EventType
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

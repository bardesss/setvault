from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from setvault_core.models.base import Base, TimestampMixin, UuidPkMixin


class Monitor(Base, UuidPkMixin, TimestampMixin):
    """A saved search ("query") or pinned source entity ("entity") polled for new content."""

    __tablename__ = "monitor"
    __table_args__ = (Index("ix_monitors_catalog", "catalog_kind", "catalog_id"),)

    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # query | entity
    query_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    per_poll_cap: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Optional link to a catalog entity (e.g. an artist) the monitor belongs to.
    catalog_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    catalog_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class MonitorDiscovery(Base, UuidPkMixin):
    """One candidate surfaced by a monitor poll. Unique per (monitor, source_kind, external_id)."""

    __tablename__ = "monitor_discovery"
    __table_args__ = (
        UniqueConstraint(
            "monitor_id",
            "source_kind",
            "external_id",
            name="uq_monitor_discovery_monitor_source_ext",
        ),
    )

    monitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitor.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    uploader: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webpage_url: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)  # high | low
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # status: auto_ingested | pending_review | ingested | dismissed
    url_rip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rip_jobs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

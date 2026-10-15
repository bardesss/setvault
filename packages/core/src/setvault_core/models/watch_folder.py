from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from setvault_core.models.base import Base, UuidPkMixin


class WatchFolder(Base, UuidPkMixin):
    __tablename__ = "watch_folders"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    host_path: Mapped[str] = mapped_column(
        String(2048), nullable=False, unique=True,
    )
    target_media_root_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_roots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Admin who configured the folder; sets ingested from it are attributed
    # to them. NULL for folders created before 0020 (falls back to first admin).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_health_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UnmatchedFile(Base, UuidPkMixin):
    """A file the ingest pipeline couldn't auto-match to an existing set or
    confidently create as a draft. Admin resolves each via the unmatched-inbox
    tab (link to set / create as draft / discard)."""

    __tablename__ = "unmatched_files"

    watch_folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("watch_folders.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    audio_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # pending | linked_to_set | created_as_draft | discarded
    resolution: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending",
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolved_to_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("live_sets.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

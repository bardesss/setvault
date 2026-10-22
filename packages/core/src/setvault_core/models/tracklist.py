from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from setvault_core.models.base import Base, TimestampMixin, UuidPkMixin

TracklistEntryStatus = Literal["raw", "resolved", "acoustid_confirmed"]
TracklistImportKind = Literal["paste", "url_1001tl", "ocr"]
TracklistImportStatus = Literal["queued", "running", "succeeded", "failed", "accepted"]


class Label(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "labels"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    external_ids: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enrichment_status: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Release(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "releases"
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    label_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labels.id", ondelete="SET NULL"), nullable=True
    )
    catalog_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    external_ids: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enrichment_status: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Track(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "tracks"
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    primary_artist_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artists.id", ondelete="SET NULL"), nullable=True
    )
    additional_artists: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    mix_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("labels.id", ondelete="SET NULL"), nullable=True
    )
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    isrc: Mapped[str | None] = mapped_column(String(16), nullable=True)
    external_ids: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enrichment_status: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ReleaseTrack(Base):
    __tablename__ = "release_tracks"
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TracklistEntry(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "tracklist_entries"
    __table_args__ = (
        UniqueConstraint(
            "live_set_id", "position",
            name="uq_tracklist_entries_live_set_position",
            deferrable=True, initially="DEFERRED",
        ),
    )
    live_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_sets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    end_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracks.id", ondelete="SET NULL"), nullable=True
    )
    raw_label: Mapped[str] = mapped_column(String(1024), nullable=False)
    mashup_with: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, nullable=False
    )
    edit_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TracklistEntryStatus] = mapped_column(String(24), nullable=False, default="raw")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    track: Mapped[Track | None] = relationship(lazy="joined")


class TracklistImportJob(Base, UuidPkMixin):
    __tablename__ = "tracklist_import_jobs"
    live_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_sets.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TracklistImportKind] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[TracklistImportStatus] = mapped_column(
        String(24), nullable=False, default="queued"
    )
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from setvault_core.models.base import Base, TimestampMixin, UuidPkMixin

VenueKind = Literal["club", "concert_hall", "arena", "outdoor", "warehouse", "boat",
                    "studio", "online", "other"]
SetType = Literal["opener", "closer", "b2b", "headline", "warmup", "unknown"]
SourceType = Literal["upload", "url_rip", "watch_folder", "search"]


class Artist(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "artists"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    bio: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    socials: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    external_ids: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enrichment_status: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artists.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merge_manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Venue(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "venues"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    kind: Mapped[VenueKind] = mapped_column(String(32), nullable=False)
    city_or_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merge_manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Series(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "series"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merge_manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Party(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "parties"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True
    )
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merge_manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    venue: Mapped[Venue | None] = relationship(lazy="joined")
    series: Mapped[Series | None] = relationship(lazy="joined")


class Tag(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "tags"
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")


class MediaRoot(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "media_roots"
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    host_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_for_ingest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    naming_template: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_health_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")


class LiveSet(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "live_sets"
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True
    )
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    set_type: Mapped[SetType] = mapped_column(String(16), nullable=False, default="unknown")
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[SourceType] = mapped_column(String(16), nullable=False, default="upload")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_root_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("media_roots.id", ondelete="RESTRICT"), nullable=False
    )
    audio_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    streaming_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    waveform_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumb_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    normalized_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_sets.id", ondelete="SET NULL"), nullable=True
    )
    # draft|processing|published|failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purge_after_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embed_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Measured on probe (services/audio_quality); all NULL until measured.
    audio_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_lossless: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quality_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quality_measured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    upgrades_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    last_upgrade_search_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    party: Mapped[Party | None] = relationship(lazy="joined")
    venue: Mapped[Venue | None] = relationship(lazy="joined")
    artists: Mapped[list[LiveSetArtist]] = relationship(
        back_populates="live_set",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="LiveSetArtist.position",
    )


class LiveSetArtist(Base):
    __tablename__ = "live_set_artists"
    live_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_sets.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="main")

    live_set: Mapped[LiveSet] = relationship(back_populates="artists")
    artist: Mapped[Artist] = relationship(lazy="joined")


class LiveSetTag(Base):
    __tablename__ = "live_set_tags"
    live_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("live_sets.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class SetFingerprint(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "set_fingerprints"
    live_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("live_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fingerprint_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    # Raw chromaprint (little-endian uint32 items, `fpcalc -raw`) for fuzzy
    # matching (services/audio_match.py); raw_version = its MATCHER_VERSION.
    raw: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_version: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

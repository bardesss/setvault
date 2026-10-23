from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from setvault_core.models.base import Base


class SystemConfig(Base):
    """Singleton row holding app-wide runtime settings.

    Enforced by the migration's ``CHECK (singleton = true)`` constraint, so
    the table always contains exactly one row. Callers read via
    ``services.system_config.get_config(session)``.
    """

    __tablename__ = "system_config"

    singleton: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    latest_release_version: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
    )
    latest_release_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True,
    )
    latest_release_etag: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    latest_release_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    audit_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90,
    )
    monitors_allow_all_users: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    monitor_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3600,
    )
    # When true AND exactly one active user exists, the app auto-authenticates
    # as that sole user (skips the login page). For trusted local/VPN use only;
    # the admin toggle is gated to the single-user case (see api/admin.py).
    single_user_auto_login: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    # Library-wide quality profile (Phase 7D): tier order best-first, cutoff
    # tier, and the automatic-upgrade switch + search cadence.
    quality_tiers_order: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False,
        default=lambda: ["lossless", "high", "good", "ok", "low"],
        server_default=text("""'["lossless","high","good","ok","low"]'::jsonb"""),
    )
    quality_cutoff: Mapped[str] = mapped_column(
        String(16), nullable=False, default="lossless", server_default="lossless",
    )
    auto_upgrades_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true(),
    )
    upgrade_search_schedule: Mapped[str] = mapped_column(
        String(8), nullable=False, default="weekly", server_default="weekly",
    )
    loudness_target_lufs: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=-14.0, server_default=text("-14.0"),
    )
    backup_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true(),
    )
    backup_time: Mapped[str] = mapped_column(
        String(5), nullable=False, default="03:30", server_default="03:30",
    )
    backup_keep: Mapped[int] = mapped_column(
        Integer, nullable=False, default=14, server_default=text("14"),
    )
    # null = use the SETVAULT_BACKUP_PATH env default
    backup_dir: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_backup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_backup_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_backup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_backup_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

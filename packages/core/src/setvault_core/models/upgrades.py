from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, exists, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from setvault_core.models.base import Base, UuidPkMixin


class SetUpgradeEvent(Base, UuidPkMixin):
    """One upgrade attempt on a set: what it was, what the candidate was, what happened."""

    __tablename__ = "set_upgrade_events"

    live_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("live_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # One of the setvault_core.triggers constants.
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # upgraded | rejected | merged
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    from_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    from_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    from_bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    from_source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    to_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    candidate_source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    candidate_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    offset_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


async def already_tried(
    session: AsyncSession, live_set_id: uuid.UUID, *, source_kind: str, external_id: str
) -> bool:
    """True if any upgrade event already exists for this set and candidate."""
    stmt = select(
        exists().where(
            SetUpgradeEvent.live_set_id == live_set_id,
            SetUpgradeEvent.candidate_source_kind == source_kind,
            SetUpgradeEvent.candidate_external_id == external_id,
        )
    )
    return bool(await session.scalar(stmt))

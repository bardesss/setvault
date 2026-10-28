from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.engagement import ListeningHistory

# A save within this gap of the previous one continues the same listen;
# a longer pause starts a new history row.
SESSION_GAP = timedelta(minutes=30)


async def record_listen(
    session: AsyncSession,
    user_id: uuid.UUID,
    live_set_id: uuid.UUID,
    position_seconds: float,
    *,
    now: datetime | None = None,
) -> ListeningHistory:
    """Append to or extend the user's listening history for a set.

    ``ended_at`` doubles as "last heard": every playback save moves it to now,
    so a listen that stops without a final save still ends at its last save.
    """
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(ListeningHistory)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.live_set_id == live_set_id,
                ListeningHistory.ended_at >= now - SESSION_GAP,
            )
            .order_by(ListeningHistory.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        row = ListeningHistory(
            user_id=user_id, live_set_id=live_set_id, started_at=now,
        )
        session.add(row)
    row.ended_at = now
    row.last_position_seconds = position_seconds
    return row

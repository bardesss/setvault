from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet
from setvault_core.models.playlists import PlayQueue
from setvault_core.services.playlists import visible_clause

MAX_QUEUE = 1000


def _dedupe(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))


async def read_queue(
    session: AsyncSession, user_id: uuid.UUID,
) -> tuple[list[LiveSet], int, datetime | None]:
    """The user's queue as the sets they can still see, the index of the
    current one among them, and when it was last written. Sets that became
    invisible are left out (the stored row isn't touched, so they return if
    restored). When the current set is gone the index moves on to the next
    visible one, clamped to the list."""
    row = await session.get(PlayQueue, user_id)
    if row is None:
        return [], 0, None
    ids = list(row.set_ids)
    found = {ls.id: ls for ls in (await session.execute(
        select(LiveSet).where(LiveSet.id.in_(ids), *visible_clause())
    )).unique().scalars()}
    sets = [found[i] for i in ids if i in found]
    before = sum(1 for i in ids[:max(row.current_index, 0)] if i in found)
    index = min(before, len(sets) - 1) if sets else 0
    return sets, index, row.updated_at


async def write_queue(
    session: AsyncSession, user_id: uuid.UUID, set_ids: list[uuid.UUID], index: int,
    base_updated_at: datetime | None,
) -> tuple[datetime, bool]:
    """Replace the queue (last write wins). ``overwrote_newer`` tells the
    caller that the stored queue was newer than the one its write was based on."""
    ids = _dedupe(set_ids)
    if len(ids) > MAX_QUEUE:
        raise ValueError(f"A queue holds at most {MAX_QUEUE} sets")
    current = set_ids[index] if 0 <= index < len(set_ids) else None
    idx = ids.index(current) if current is not None else 0
    stored = (await session.execute(
        select(PlayQueue.updated_at).where(PlayQueue.user_id == user_id)
    )).scalar_one_or_none()
    if base_updated_at is not None and base_updated_at.tzinfo is None:
        base_updated_at = base_updated_at.replace(tzinfo=UTC)
    overwrote = stored is not None and (base_updated_at is None or base_updated_at < stored)
    now = datetime.now(UTC)
    stmt = insert(PlayQueue).values(
        user_id=user_id, set_ids=ids, current_index=idx, updated_at=now)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[PlayQueue.user_id],
        set_={"set_ids": stmt.excluded.set_ids, "current_index": stmt.excluded.current_index,
              "updated_at": stmt.excluded.updated_at},
    ).execution_options(synchronize_session=False))
    return now, overwrote


async def repoint_for_merge(
    session: AsyncSession, *, loser_id: uuid.UUID, survivor_id: uuid.UUID,
) -> None:
    """Swap the loser for the survivor in every queue, keeping the first
    occurrence. A queue that was on the loser follows the survivor."""
    rows = (await session.execute(
        select(PlayQueue).where(PlayQueue.set_ids.contains([loser_id]))
    )).scalars().all()
    for q in rows:
        old = list(q.set_ids)
        current = old[q.current_index] if 0 <= q.current_index < len(old) else None
        if current == loser_id:
            current = survivor_id
        new = _dedupe([survivor_id if i == loser_id else i for i in old])
        q.set_ids = new
        q.current_index = new.index(current) if current in new else 0
        q.updated_at = datetime.now(UTC)
    await session.flush()

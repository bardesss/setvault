from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, bindparam, delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet
from setvault_core.models.playlists import Playlist, PlaylistItem

MAX_ITEMS = 1000


class PlaylistError(ValueError):
    """A playlist change that breaks a rule (cap, or a reorder that doesn't
    match the playlist)."""


def visible_clause() -> tuple:
    """Sets a listener may see: published and not in the recycle bin."""
    return (LiveSet.deleted_at.is_(None), LiveSet.status == "published")


def _touch(playlist: Playlist) -> None:
    playlist.updated_at = datetime.now(UTC)


async def _densify(session: AsyncSession, playlist_id: uuid.UUID) -> None:
    """Rewrite positions as 0..n-1, keeping the current order."""
    await session.execute(
        text(
            "UPDATE playlist_items pi SET position = r.rn - 1 FROM ("
            " SELECT live_set_id, row_number() OVER ("
            "  ORDER BY position, added_at, live_set_id) AS rn"
            " FROM playlist_items WHERE playlist_id = :pid"
            ") r WHERE pi.playlist_id = :pid AND pi.live_set_id = r.live_set_id"
        ),
        {"pid": playlist_id},
    )


async def get_owned(
    session: AsyncSession, user_id: uuid.UUID, playlist_id: uuid.UUID,
) -> Playlist | None:
    return (await session.execute(
        select(Playlist).where(Playlist.id == playlist_id, Playlist.owner_user_id == user_id)
    )).scalar_one_or_none()


async def list_owned(
    session: AsyncSession, user_id: uuid.UUID,
) -> list[tuple[Playlist, int, int]]:
    """The user's playlists, most recently changed first, with the number and
    total length of the sets listeners can see."""
    rows = (await session.execute(
        select(
            Playlist,
            func.count(LiveSet.id),
            func.coalesce(func.sum(func.coalesce(LiveSet.duration_seconds, 0)), 0),
        )
        .outerjoin(PlaylistItem, PlaylistItem.playlist_id == Playlist.id)
        .outerjoin(
            LiveSet, and_(LiveSet.id == PlaylistItem.live_set_id, *visible_clause())
        )
        .where(Playlist.owner_user_id == user_id)
        .group_by(Playlist.id)
        .order_by(Playlist.updated_at.desc(), Playlist.id)
    )).all()
    return [(pl, int(n), int(total)) for pl, n, total in rows]


async def visible_items(
    session: AsyncSession, playlist_id: uuid.UUID,
) -> list[tuple[LiveSet, PlaylistItem]]:
    rows = (await session.execute(
        select(LiveSet, PlaylistItem)
        .join(PlaylistItem, PlaylistItem.live_set_id == LiveSet.id)
        .where(PlaylistItem.playlist_id == playlist_id, *visible_clause())
        .order_by(PlaylistItem.position)
    )).unique().all()
    return [(ls, item) for ls, item in rows]


async def add_item(session: AsyncSession, playlist: Playlist, live_set_id: uuid.UUID) -> bool:
    """Append a set. False when it is already in the playlist."""
    present = (await session.execute(
        select(PlaylistItem.live_set_id).where(
            PlaylistItem.playlist_id == playlist.id, PlaylistItem.live_set_id == live_set_id)
    )).first()
    if present is not None:
        return False
    count, top = (await session.execute(
        select(func.count(), func.coalesce(func.max(PlaylistItem.position), -1))
        .where(PlaylistItem.playlist_id == playlist.id)
    )).one()
    if count >= MAX_ITEMS:
        raise PlaylistError(f"A playlist holds at most {MAX_ITEMS} sets")
    res = await session.execute(
        insert(PlaylistItem)
        .values(playlist_id=playlist.id, live_set_id=live_set_id, position=top + 1)
        .on_conflict_do_nothing()
    )
    if not res.rowcount:
        return False
    _touch(playlist)
    await session.flush()
    return True


async def remove_item(session: AsyncSession, playlist: Playlist, live_set_id: uuid.UUID) -> bool:
    res = await session.execute(
        delete(PlaylistItem).where(
            PlaylistItem.playlist_id == playlist.id, PlaylistItem.live_set_id == live_set_id)
    )
    if not res.rowcount:
        return False
    await _densify(session, playlist.id)
    _touch(playlist)
    await session.flush()
    return True


async def reorder(
    session: AsyncSession, playlist: Playlist, visible_set_ids: list[uuid.UUID],
) -> None:
    """Put the visible sets in the given order; hidden ones (draft, recycled)
    keep their rows and follow, in their old relative order. The list must be
    exactly the playlist's current visible sets, so a stale list is refused
    instead of silently dropping an item."""
    rows = (await session.execute(
        select(PlaylistItem.live_set_id, LiveSet.id.is_not(None))
        .outerjoin(LiveSet, and_(LiveSet.id == PlaylistItem.live_set_id, *visible_clause()))
        .where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    )).all()
    visible = {sid for sid, vis in rows if vis}
    if len(visible_set_ids) != len(visible) or set(visible_set_ids) != visible:
        raise PlaylistError("The list doesn't match the sets in this playlist")
    order = [*visible_set_ids, *(sid for sid, vis in rows if not vis)]
    await session.execute(
        update(PlaylistItem.__table__)
        .where(
            PlaylistItem.playlist_id == bindparam("b_pid"),
            PlaylistItem.live_set_id == bindparam("b_sid"),
        )
        .values(position=bindparam("b_pos"))
        .execution_options(synchronize_session=False),
        [{"b_pid": playlist.id, "b_sid": sid, "b_pos": pos} for pos, sid in enumerate(order)],
    )
    _touch(playlist)
    await session.flush()


async def repoint_for_merge(
    session: AsyncSession, *, loser_id: uuid.UUID, survivor_id: uuid.UUID,
) -> None:
    """Move the loser's playlist entries to the survivor. Where a playlist has
    both, one survivor row stays at the earlier position."""
    rows = (await session.execute(
        select(PlaylistItem.playlist_id, PlaylistItem.position)
        .where(PlaylistItem.live_set_id == loser_id)
    )).all()
    for playlist_id, loser_pos in rows:
        surv_pos = (await session.execute(
            select(PlaylistItem.position).where(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.live_set_id == survivor_id)
        )).scalar_one_or_none()
        if surv_pos is None:
            await session.execute(
                update(PlaylistItem)
                .where(PlaylistItem.playlist_id == playlist_id,
                       PlaylistItem.live_set_id == loser_id)
                .values(live_set_id=survivor_id)
                .execution_options(synchronize_session=False)
            )
        else:
            await session.execute(
                update(PlaylistItem)
                .where(PlaylistItem.playlist_id == playlist_id,
                       PlaylistItem.live_set_id == survivor_id)
                .values(position=min(surv_pos, loser_pos))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(PlaylistItem)
                .where(PlaylistItem.playlist_id == playlist_id,
                       PlaylistItem.live_set_id == loser_id)
                .execution_options(synchronize_session=False)
            )
        await _densify(session, playlist_id)
        await session.execute(
            update(Playlist).where(Playlist.id == playlist_id)
            .values(updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )


async def playlists_containing(
    session: AsyncSession, user_id: uuid.UUID, live_set_id: uuid.UUID,
) -> list[tuple[Playlist, bool]]:
    """All the user's playlists by name, flagged when they hold the set."""
    has = exists().where(
        PlaylistItem.playlist_id == Playlist.id, PlaylistItem.live_set_id == live_set_id)
    rows = (await session.execute(
        select(Playlist, has.label("contains"))
        .where(Playlist.owner_user_id == user_id)
        .order_by(func.lower(Playlist.name), Playlist.id)
    )).all()
    return [(pl, bool(c)) for pl, c in rows]
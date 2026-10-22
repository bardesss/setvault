from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet
from setvault_core.models.engagement import Favorite


async def add_favorite(session: AsyncSession, user_id: uuid.UUID, live_set_id: uuid.UUID) -> None:
    """Idempotent: favouriting twice leaves one row."""
    await session.execute(
        insert(Favorite)
        .values(user_id=user_id, live_set_id=live_set_id)
        .on_conflict_do_nothing()
    )


async def remove_favorite(
    session: AsyncSession, user_id: uuid.UUID, live_set_id: uuid.UUID,
) -> None:
    """Idempotent: removing a non-favourite is a no-op."""
    await session.execute(
        delete(Favorite).where(
            Favorite.user_id == user_id, Favorite.live_set_id == live_set_id
        )
    )


async def is_favorite(session: AsyncSession, user_id: uuid.UUID, live_set_id: uuid.UUID) -> bool:
    return (
        await session.execute(
            select(Favorite.live_set_id).where(
                Favorite.user_id == user_id, Favorite.live_set_id == live_set_id
            )
        )
    ).first() is not None


async def list_favorites(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int,
) -> tuple[list[tuple[LiveSet, datetime]], int]:
    """Published, non-deleted favourites, newest favourited first, plus total."""
    conds = (
        Favorite.user_id == user_id,
        LiveSet.deleted_at.is_(None),
        LiveSet.status == "published",
    )
    total = (
        await session.execute(
            select(func.count())
            .select_from(Favorite)
            .join(LiveSet, LiveSet.id == Favorite.live_set_id)
            .where(*conds)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(LiveSet, Favorite.created_at)
            .join(Favorite, Favorite.live_set_id == LiveSet.id)
            .where(*conds)
            .order_by(Favorite.created_at.desc(), LiveSet.id)
            .limit(limit)
            .offset(offset)
        )
    ).unique().all()
    return [(ls, fav_at) for ls, fav_at in rows], int(total)

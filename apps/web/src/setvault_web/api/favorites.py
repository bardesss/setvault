from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.schemas.favorites import FavoriteItemOut, FavoritesListOut
from setvault_core.services.favorites import add_favorite, list_favorites, remove_favorite
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.api.sets import summary_out, tags_by_set
from setvault_web.deps import current_user, db_session

router = APIRouter(tags=["favorites"])


async def _live_or_404(session: AsyncSession, slug: str) -> LiveSet:
    live = (await session.execute(
        select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404)
    return live


@router.put("/api/sets/{slug}/favorite", status_code=204)
async def favorite_set(
    slug: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _live_or_404(session, slug)
    await add_favorite(session, user.id, live.id)
    await session.commit()


@router.delete("/api/sets/{slug}/favorite", status_code=204)
async def unfavorite_set(
    slug: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = await _live_or_404(session, slug)
    await remove_favorite(session, user.id, live.id)
    await session.commit()


@router.get("/api/me/favorites", response_model=FavoritesListOut)
async def my_favorites(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await list_favorites(session, user.id, limit=limit, offset=offset)
    tags = await tags_by_set(session, [ls.id for ls, _ in rows])
    items = [
        FavoriteItemOut(
            **summary_out(ls, tags.get(ls.id, [])).model_dump(), favorited_at=fav_at,
        )
        for ls, fav_at in rows
    ]
    return FavoritesListOut(items=items, total=total)

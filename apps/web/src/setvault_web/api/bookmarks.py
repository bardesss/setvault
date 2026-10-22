from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.catalog import LiveSet
from setvault_core.models.engagement_3c import Bookmark
from setvault_core.models.identity import User
from setvault_core.schemas.bookmarks import (
    BookmarkCreateIn,
    BookmarkOut,
    BookmarksListOut,
)
from setvault_core.services.bookmarks import (
    create_bookmark,
    list_bookmarks_for_set,
    list_bookmarks_for_user,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, parse_uuid

router = APIRouter(tags=["bookmarks"])


def _out(b: Bookmark, slug: str | None = None, title: str | None = None) -> BookmarkOut:
    return BookmarkOut(
        id=str(b.id),
        live_set_id=str(b.live_set_id),
        live_set_slug=slug,
        live_set_title=title,
        position_seconds=b.position_seconds,
        label=b.label,
        created_at=b.created_at,
    )


@router.get("/api/sets/{slug}/bookmarks", response_model=BookmarksListOut)
async def list_for_set(
    slug: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = (await session.execute(
        select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404)
    rows = await list_bookmarks_for_set(session, user.id, live.id)
    return BookmarksListOut(items=[_out(b) for b in rows])


@router.post("/api/sets/{slug}/bookmarks", response_model=BookmarkOut, status_code=201)
async def create_for_set(
    slug: str,
    body: BookmarkCreateIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = (await session.execute(
        select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404)
    try:
        b = await create_bookmark(
            session, user_id=user.id, live_set_id=live.id,
            position_seconds=body.position_seconds, label=body.label,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="bookmark already exists") from exc
    await session.commit()
    return _out(b)


@router.delete("/api/sets/{slug}/bookmarks/{bookmark_id}", status_code=204)
async def delete_bookmark(
    slug: str, bookmark_id: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    b = await session.get(Bookmark, parse_uuid(bookmark_id))
    if b is None or b.user_id != user.id:
        raise HTTPException(status_code=404)
    await session.delete(b)
    await session.commit()


@router.get("/api/me/bookmarks", response_model=BookmarksListOut)
async def my_bookmarks(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = await list_bookmarks_for_user(session, user.id)
    out: list[BookmarkOut] = []
    set_ids = list({b.live_set_id for b in rows})
    sets = {s.id: s for s in (await session.execute(
        select(LiveSet).where(LiveSet.id.in_(set_ids))
    )).scalars().all()} if set_ids else {}
    for b in rows:
        s = sets.get(b.live_set_id)
        out.append(_out(b, slug=s.slug if s else None, title=s.title if s else None))
    return BookmarksListOut(items=out)

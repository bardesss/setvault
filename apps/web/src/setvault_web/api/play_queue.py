from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.schemas.playlists import QueueIn, QueueOut, QueueWriteOut
from setvault_core.services import play_queue as svc
from setvault_core.services.playlists import visible_clause
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session

router = APIRouter(tags=["play-queue"])


@router.get("/api/me/queue", response_model=QueueOut)
async def get_queue(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    sets, index, updated_at = await svc.read_queue(session, user.id)
    return QueueOut(slugs=[ls.slug for ls in sets], index=index, updated_at=updated_at)


@router.put("/api/me/queue", response_model=QueueWriteOut)
async def put_queue(
    body: QueueIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    if len(body.slugs) > svc.MAX_QUEUE:
        raise HTTPException(
            status_code=400, detail=f"A queue holds at most {svc.MAX_QUEUE} sets")
    found = dict((await session.execute(
        select(LiveSet.slug, LiveSet.id).where(
            LiveSet.slug.in_(body.slugs), *visible_clause())
    )).all())
    # Slugs that aren't visible sets are dropped. The index follows its slug;
    # if that one was dropped it lands on the entry that took its place, and
    # is clamped so the service always gets a valid index.
    kept = [found[s] for s in body.slugs if s in found]
    before = sum(1 for s in body.slugs[:body.index] if s in found)
    index = max(0, min(before, len(kept) - 1))
    updated_at, overwrote = await svc.write_queue(
        session, user.id, kept, index, body.base_updated_at)
    await session.commit()
    return QueueWriteOut(updated_at=updated_at, overwrote_newer=overwrote)

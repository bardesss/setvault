from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from setvault_core.models.catalog import Artist
from setvault_core.models.tracklist import Track
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, parse_uuid

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


class TrackOut(BaseModel):
    id: str
    title: str
    artist_name: str | None


@router.get("/{track_id}", response_model=TrackOut)
async def get_track(
    track_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
):
    """A track's title and primary artist, for the library's track filter."""
    row = (await session.execute(
        select(Track.id, Track.title, Artist.name)
        .outerjoin(Artist, Artist.id == Track.primary_artist_id)
        .where(Track.id == parse_uuid(track_id))
    )).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="track not found")
    return TrackOut(id=str(row[0]), title=row[1], artist_name=row[2])

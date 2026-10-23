"""Public read-only set-detail endpoint for the /embed/[slug] route.

Returns 404 for sets where embed_allowed is false - same response as a
non-existent set so the toggle state isn't leaked.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.catalog import LiveSet
from setvault_core.models.tracklist import TracklistEntry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.api.sets import stream_url
from setvault_web.deps import db_session

router = APIRouter(tags=["embed"])


@router.get("/api/sets/{slug}/embed")
async def embed_set(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = (await session.execute(
        select(LiveSet).where(
            LiveSet.slug == slug,
            LiveSet.deleted_at.is_(None),
            LiveSet.embed_allowed.is_(True),
            LiveSet.status == "published",
        )
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404)

    entries = (await session.execute(
        select(TracklistEntry).where(TracklistEntry.live_set_id == live.id)
        .order_by(TracklistEntry.position)
    )).scalars().all()

    return {
        "slug": live.slug,
        "title": live.title,
        "duration_seconds": live.duration_seconds,
        "audio_url": stream_url(live),
        "waveform_url": f"/api/sets/{slug}/waveform",
        "tracklist": [
            {"position": e.position, "start_seconds": e.start_seconds,
             "label": e.raw_label}
            for e in entries
        ],
    }

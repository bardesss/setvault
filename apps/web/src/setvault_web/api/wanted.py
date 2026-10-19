"""Admin Wanted list: sets still below the quality cutoff (Phase 7D).

  - GET  /api/admin/wanted: published sets with upgrades on whose measured
    tier is below the cutoff, least-recently searched first, each with the
    last upgrade attempt on it.
  - POST /api/admin/wanted/{slug}/search: look for a better copy now.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.jobs.upgrade_search import enqueue_search_upgrade_now
from setvault_core.models.catalog import LiveSet
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.services.audio_quality import quality_label
from setvault_core.services.quality_profile import cutoff_unmet, get_profile, rank
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import db_session, require_admin

router = APIRouter(prefix="/api/admin/wanted", tags=["admin"])


@router.get("")
async def list_wanted(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
    limit: int = 100,
):
    limit = max(1, min(limit, 500))
    profile = await get_profile(session)
    if profile.cutoff not in profile.order:
        return {"items": []}
    at_or_above = list(profile.order[: rank(profile, profile.cutoff) + 1])
    rows = (await session.execute(
        select(LiveSet)
        .where(
            LiveSet.status == "published",
            LiveSet.deleted_at.is_(None),
            LiveSet.upgrades_enabled.is_(True),
            LiveSet.quality_tier.is_not(None),
            LiveSet.quality_tier.not_in(at_or_above),
        )
        .order_by(
            LiveSet.last_upgrade_search_at.asc().nulls_first(),
            LiveSet.created_at, LiveSet.id,
        )
        .limit(limit)
    )).unique().scalars().all()

    last: dict = {}
    if rows:
        events = (await session.execute(
            select(SetUpgradeEvent)
            .where(SetUpgradeEvent.live_set_id.in_([r.id for r in rows]))
            .order_by(SetUpgradeEvent.created_at.asc())
        )).scalars()
        for ev in events:  # ascending, so the newest per set wins
            last[ev.live_set_id] = ev

    return {"items": [
        {
            "id": str(live.id),
            "slug": live.slug,
            "title": live.title,
            "quality_label": quality_label(
                live.quality_tier, live.audio_codec, live.audio_bitrate_kbps,
                live.source_type,
            ),
            "quality_tier": live.quality_tier,
            "last_upgrade_search_at": (
                live.last_upgrade_search_at.isoformat()
                if live.last_upgrade_search_at else None
            ),
            "last_event": None if live.id not in last else {
                "outcome": last[live.id].outcome,
                "reason": last[live.id].reason,
                "created_at": last[live.id].created_at.isoformat(),
            },
        }
        for live in rows
    ]}


@router.post("/{slug}/search", status_code=202)
async def search_now(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    live = (await session.execute(
        select(LiveSet).where(
            LiveSet.slug == slug, LiveSet.status == "published",
            LiveSet.deleted_at.is_(None),
        )
    )).unique().scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="set not found")
    profile = await get_profile(session)
    if not cutoff_unmet(profile, live.quality_tier):
        raise HTTPException(status_code=409, detail="set already meets the quality cutoff")
    queued = enqueue_search_upgrade_now(live.id)
    return {"status": "queued" if queued else "already_queued"}

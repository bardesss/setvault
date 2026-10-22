"""Admin Wanted list: sets still below the quality cutoff (Phase 7D).

  - GET  /api/admin/wanted: the sets the upgrade schedule searches
    (``wanted_filter``: published, upgrades on, measured below the cutoff,
    fingerprinted, not a kept duplicate), least-recently searched first,
    each with the last upgrade attempt on it, plus
    ``unfingerprinted_below_cutoff``: sets that would be wanted but still
    need a fingerprint (the Quality tab backfill).
  - POST /api/admin/wanted/{slug}/search: look for a better copy now.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.jobs.upgrade_search import (
    enqueue_search_upgrade_now,
    unfingerprinted_wanted_filter,
    wanted_filter,
)
from setvault_core.models.catalog import LiveSet, SetFingerprint
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.services.audio_match import MATCHER_VERSION
from setvault_core.services.audio_quality import quality_label
from setvault_core.services.notifications import source_name
from setvault_core.services.quality_profile import cutoff_unmet, get_profile
from sqlalchemy import func, select
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
    rows = (await session.execute(
        select(LiveSet)
        .where(wanted_filter(profile))
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
            # id breaks ties between events written in one transaction.
            .order_by(SetUpgradeEvent.created_at.asc(), SetUpgradeEvent.id.asc())
        )).scalars()
        for ev in events:  # ascending, so the newest per set wins
            last[ev.live_set_id] = ev

    # Below the cutoff but not searchable until the backfill fingerprints
    # them; the page says so instead of claiming every set meets the cutoff.
    unfingerprinted = (await session.execute(
        select(func.count()).select_from(LiveSet)
        .where(unfingerprinted_wanted_filter(profile))
    )).scalar_one()

    return {"unfingerprinted_below_cutoff": int(unfingerprinted), "items": [
        {
            "id": str(live.id),
            "slug": live.slug,
            "title": live.title,
            "quality_label": quality_label(
                live.quality_tier, live.audio_codec, live.audio_bitrate_kbps,
                source_name(live.source_type, live.source_url),
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
    if not live.upgrades_enabled:
        raise HTTPException(status_code=409, detail="upgrades are off for this set")
    if live.duplicate_of is not None:
        # A kept duplicate is never searched (due_sets); its original is.
        raise HTTPException(status_code=409, detail="set is a duplicate of another set")
    if live.quality_tier is None:
        raise HTTPException(status_code=409, detail="quality not measured yet")
    profile = await get_profile(session)
    if not cutoff_unmet(profile, live.quality_tier):
        raise HTTPException(status_code=409, detail="set already meets the quality cutoff")
    # Without a current-version raw fingerprint every candidate is rejected as
    # "different audio" and burned, so wait for the fingerprint job.
    has_fp = (await session.execute(
        select(SetFingerprint.id).where(
            SetFingerprint.live_set_id == live.id,
            SetFingerprint.raw.is_not(None),
            SetFingerprint.raw_version == MATCHER_VERSION,
        ).limit(1)
    )).first()
    if has_fp is None:
        raise HTTPException(status_code=409, detail="not fingerprinted yet")
    queued = enqueue_search_upgrade_now(live.id)
    return {"status": "queued" if queued else "already_queued"}

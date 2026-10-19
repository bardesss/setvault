"""Admin review queue for fingerprint duplicates.

The pipeline's fingerprint stage flags an arrival whose audio matches an
existing set (``LiveSet.duplicate_of``) and ``mark_ready`` holds it as a
draft instead of publishing it. These endpoints let the admin resolve them:

  - **GET  /api/admin/duplicates** — held duplicates, newest first, each with
    the set it duplicates.
  - **POST /api/admin/duplicates/{slug}/keep** — publish it anyway (e.g. a
    different recording that happens to fingerprint the same).
  - **POST /api/admin/duplicates/{slug}/discard** — move it to the recycle
    bin; the scheduled purge job removes it after the usual grace window.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.jobs.ready import fan_out_webhooks, publish_live_set
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.services.audit import log as audit_log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from setvault_web.deps import current_user, db_session, require_admin

router = APIRouter(prefix="/api/admin/duplicates", tags=["admin"])

# Same grace window as a manual delete (sets.py delete_set).
_RECYCLE_GRACE = timedelta(days=14)


def _held_duplicates():
    return select(LiveSet).where(
        LiveSet.duplicate_of.is_not(None),
        LiveSet.status == "draft",
        LiveSet.deleted_at.is_(None),
    )


async def _get_held(session: AsyncSession, slug: str) -> LiveSet:
    live = (await session.execute(
        _held_duplicates().where(LiveSet.slug == slug),
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not a held duplicate")
    return live


@router.get("")
async def list_duplicates(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
    limit: int = 100,
):
    original = aliased(LiveSet)
    rows = (await session.execute(
        _held_duplicates()
        .add_columns(original)
        .outerjoin(original, original.id == LiveSet.duplicate_of)
        .order_by(LiveSet.created_at.desc())
        .limit(limit)
    )).all()
    return {"items": [
        {
            "id": str(dup.id),
            "slug": dup.slug,
            "title": dup.title,
            "source_type": dup.source_type,
            "duration_seconds": dup.duration_seconds,
            "created_at": dup.created_at.isoformat() if dup.created_at else None,
            "original": None if orig is None else {
                "slug": orig.slug,
                "title": orig.title,
                "status": orig.status,
                "duration_seconds": orig.duration_seconds,
            },
        }
        for dup, orig in rows
    ]}


@router.post("/{slug}/keep")
async def keep_duplicate(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    live = await _get_held(session, slug)
    live.duplicate_kept_at = datetime.now(UTC)
    await publish_live_set(session, live)
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="set.duplicate_kept",
        target_type="LiveSet",
        target_id=str(live.id),
        after={"duplicate_of": str(live.duplicate_of), "status": live.status},
    )
    await session.commit()
    await fan_out_webhooks(live, "set.published")
    return {"slug": live.slug, "status": live.status}


@router.post("/{slug}/discard", status_code=204)
async def discard_duplicate(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    live = await _get_held(session, slug)
    now = datetime.now(UTC)
    live.deleted_at = now
    live.purge_after_at = now + _RECYCLE_GRACE
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="set.duplicate_discarded",
        target_type="LiveSet",
        target_id=str(live.id),
        after={"duplicate_of": str(live.duplicate_of)},
    )
    await session.commit()

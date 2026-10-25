"""Admin view of sets that never reached Library.

A set stays a draft while the pipeline works on it, when it is held as a
fingerprint duplicate (also on the Duplicates page), or when its rip or
processing failed part-way. Library and search list published sets only,
so without this page those drafts are invisible.

  - **GET  /api/admin/drafts** — every draft not in the recycle bin, newest
    first, with whether it is ready to publish (has a stream), still being
    processed (its rip is running), and its last rip's status and error.
  - **POST /api/admin/drafts/{slug}/publish** — publish a ready draft. A held
    duplicate is kept, as on the Duplicates page.
  - **POST /api/admin/drafts/{slug}/discard** — move it to the recycle bin;
    the scheduled purge job removes it after the usual grace window.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.jobs.ready import fan_out_webhooks, publish_live_set
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.models.url_rip import RipJob
from setvault_core.services.audit import log as audit_log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from setvault_web.deps import db_session, require_admin

router = APIRouter(prefix="/api/admin/drafts", tags=["admin"])

# Same grace window as a manual delete (sets.py delete_set).
_RECYCLE_GRACE = timedelta(days=14)
# A rip in any other state is still running.
_RIP_DONE = ("ready", "failed")


def _drafts():
    return select(LiveSet).where(LiveSet.status == "draft", LiveSet.deleted_at.is_(None))


async def _last_rips(session: AsyncSession, ids: list) -> dict:
    """The newest RipJob per set, for the sets in ``ids``."""
    if not ids:
        return {}
    rows = (await session.execute(
        select(RipJob).where(RipJob.live_set_id.in_(ids)).order_by(RipJob.created_at)
    )).scalars().all()
    return {r.live_set_id: r for r in rows}  # later rows win


def _processing(rip: RipJob | None) -> bool:
    return rip is not None and rip.status not in _RIP_DONE


async def _get_draft(session: AsyncSession, slug: str) -> LiveSet:
    live = (await session.execute(
        # of=LiveSet: the eager-loaded outer joins can't be locked.
        _drafts().where(LiveSet.slug == slug).with_for_update(of=LiveSet)
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not a draft")
    return live


@router.get("")
async def list_drafts(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
    limit: int = 200,
):
    original = aliased(LiveSet)
    rows = (await session.execute(
        _drafts()
        .add_columns(original)
        .outerjoin(original, original.id == LiveSet.duplicate_of)
        .order_by(LiveSet.created_at.desc())
        .limit(limit)
    )).all()
    rips = await _last_rips(session, [live.id for live, _o in rows])
    items = []
    for live, orig in rows:
        rip = rips.get(live.id)
        items.append({
            "id": str(live.id),
            "slug": live.slug,
            "title": live.title,
            "source_type": live.source_type,
            "duration_seconds": live.duration_seconds,
            "created_at": live.created_at.isoformat() if live.created_at else None,
            "ready": live.streaming_path is not None,
            "processing": _processing(rip),
            "rip_status": rip.status if rip else None,
            "error": rip.error_text if rip else None,
            "duplicate_of": None if orig is None else {"slug": orig.slug, "title": orig.title},
        })
    return {"items": items}


@router.post("/{slug}/publish")
async def publish_draft(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
):
    live = await _get_draft(session, slug)
    if live.streaming_path is None:
        raise HTTPException(
            status_code=409,
            detail="This set has no playable stream yet, so it can't be published.",
        )
    if live.duplicate_of is not None:
        live.duplicate_kept_at = datetime.now(UTC)
    await publish_live_set(session, live)
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="set.draft_published",
        target_type="LiveSet",
        target_id=str(live.id),
        after={"status": live.status},
    )
    await session.commit()
    await fan_out_webhooks(live, "set.published")
    return {"slug": live.slug, "status": live.status}


@router.post("/{slug}/discard")
async def discard_draft(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
):
    live = await _get_draft(session, slug)
    rip = (await _last_rips(session, [live.id])).get(live.id)
    if _processing(rip):
        raise HTTPException(
            status_code=409,
            detail="This set is still being processed. Try again when it's done.",
        )
    now = datetime.now(UTC)
    live.deleted_at = now
    live.purge_after_at = now + _RECYCLE_GRACE
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="set.draft_discarded",
        target_type="LiveSet",
        target_id=str(live.id),
        after={"purge_after_at": live.purge_after_at.isoformat()},
    )
    await session.commit()
    return {"slug": slug, "outcome": "recycled"}

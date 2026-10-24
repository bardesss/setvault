"""Admin recycle-bin endpoints (§J8).

The scheduled ``purge_recycle_bin`` worker job (from Phase 5B) handles
automatic cleanup; these endpoints give the admin per-row manual control:

  - **GET  /api/admin/recycle** — list soft-deleted sets newest-first.
  - **POST /api/admin/recycle/{slug}/restore** — clear ``deleted_at`` +
    ``purge_after_at`` so the set re-appears in the library; a set that
    has no stream yet (recycled before its first transcode) gets one queued.
  - **POST /api/admin/recycle/{slug}/purge-now** — immediate hard-delete
    (audio files removed + LiveSet row dropped + ``set.purged`` audit
    event), bypassing the grace window.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.jobs.transcode import enqueue_transcode
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.services.audit import log as audit_log
from setvault_core.services.storage import path_in_use, resolve_set_path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/recycle", tags=["admin"])


def _set_to_dict(live: LiveSet) -> dict:
    return {
        "id": str(live.id),
        "slug": live.slug,
        "title": live.title,
        "deleted_at": live.deleted_at.isoformat() if live.deleted_at else None,
        "purge_after_at": (
            live.purge_after_at.isoformat() if live.purge_after_at else None
        ),
        "audio_path": live.audio_path,
        "duration_seconds": live.duration_seconds,
    }


@router.get("")
async def list_recycled(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
    limit: int = 100,
):
    rows = (await session.execute(
        select(LiveSet)
        .where(LiveSet.deleted_at.is_not(None))
        .order_by(LiveSet.deleted_at.desc())
        .limit(limit)
    )).scalars().all()
    return {"items": [_set_to_dict(r) for r in rows]}


@router.post("/{slug}/restore")
async def restore_set(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    live = (await session.execute(
        select(LiveSet)
        .where(LiveSet.slug == slug, LiveSet.deleted_at.is_not(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not in recycle bin")
    before = {
        "deleted_at": live.deleted_at.isoformat() if live.deleted_at else None,
        "purge_after_at": (
            live.purge_after_at.isoformat() if live.purge_after_at else None
        ),
    }
    live.deleted_at = None
    live.purge_after_at = None
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="set.restored",
        target_type="LiveSet",
        target_id=str(live.id),
        before=before,
    )
    # A set recycled before (or during) its first transcode has no stream,
    # and nothing else makes one: regain skips sets without a stream.
    needs_stream = live.streaming_path is None and await _audio_exists(session, live)
    await session.commit()
    if needs_stream:
        enqueue_transcode(live.id)
    return _set_to_dict(live)


async def _audio_exists(session: AsyncSession, live: LiveSet) -> bool:
    root = await session.get(MediaRoot, live.media_root_id)
    if root is None or not live.audio_path:
        return False
    try:
        return resolve_set_path(root.host_path, live.audio_path).is_file()
    except (ValueError, OSError):
        return False


def _try_unlink(path: Path) -> bool:
    try:
        if path.exists():
            path.unlink()
        return True
    except OSError as exc:
        logger.warning("purge-now: unlink failed for %s: %s", path, exc)
        return False


@router.post("/{slug}/purge-now", status_code=204)
async def purge_now(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    """Immediate hard-delete. Same logic as the hourly purge job but for
    one specific row, bypassing the ``purge_after_at`` grace window."""
    live = (await session.execute(
        select(LiveSet)
        .where(LiveSet.slug == slug, LiveSet.deleted_at.is_not(None))
    )).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not in recycle bin")

    root = await session.get(MediaRoot, live.media_root_id)
    if root is not None:
        host_root = Path(root.host_path)
        for rel in (live.audio_path, live.streaming_path,
                    live.waveform_path, live.thumb_path):
            if not rel:
                continue
            # Never delete a file another set still points at (quality upgrade).
            if await path_in_use(session, live.media_root_id, rel,
                                 exclude_live_set_id=live.id):
                logger.info("purge-now: keeping %s, another set uses it", rel)
                continue
            _try_unlink(host_root / rel)

    await audit_log(
        session,
        actor_user_id=admin.id,
        action="set.purged",
        target_type="LiveSet",
        target_id=str(live.id),
        before={"slug": live.slug, "title": live.title},
    )
    await session.delete(live)
    await session.commit()

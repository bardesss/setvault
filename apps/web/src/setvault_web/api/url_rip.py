from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.models.url_rip import RipJob
from setvault_core.schemas.url_rip import RipJobOut, RipJobsListOut, RipSubmitIn
from setvault_core.services import url_rip as _service
from setvault_core.services.audit import log as audit_log
from setvault_core.services.rip_enqueue import enqueue_rip
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session
from setvault_web.rate_limit import hit as _ratelimit_hit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["url_rip"])

_RIP_HOURLY_LIMIT = 5
_RIP_DAILY_LIMIT = 50


async def _enforce_rip_rate_limit(user_id: uuid.UUID) -> None:
    """Per-user URL-rip submission limit: 5/hour and 50/day."""
    hourly = await _ratelimit_hit(f"rip_hour:{user_id}",
                                  limit=_RIP_HOURLY_LIMIT, window_seconds=3600)
    if hourly > _RIP_HOURLY_LIMIT:
        raise HTTPException(
            status_code=429, detail="too many URL rips this hour",
            headers={"Retry-After": "3600"},
        )
    daily = await _ratelimit_hit(f"rip_day:{user_id}",
                                 limit=_RIP_DAILY_LIMIT, window_seconds=86400)
    if daily > _RIP_DAILY_LIMIT:
        raise HTTPException(
            status_code=429, detail="too many URL rips today",
            headers={"Retry-After": "86400"},
        )


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _to_out(job: RipJob, *, live_set_slug: str | None = None) -> RipJobOut:
    return RipJobOut(
        id=str(job.id),
        live_set_id=str(job.live_set_id) if job.live_set_id else None,
        live_set_slug=live_set_slug,
        source_url=job.source_url,
        source_external_id=job.source_external_id,
        source_platform=job.source_platform,
        status=job.status,
        progress_pct=job.progress_pct,
        message=job.message,
        error_text=job.error_text,
        probed_metadata=job.probed_metadata or {},
        ytdlp_version=job.ytdlp_version,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/api/sets/url-rip", response_model=RipJobOut, status_code=201)
async def submit_url_rip(
    body: RipSubmitIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    await _enforce_rip_rate_limit(user.id)
    try:
        job = await _service.submit_rip(
            session, user_id=user.id, url=body.url, trigger=body.trigger,
        )
    except _service.DuplicateRipError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"rip already in progress: {exc.existing.id}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await audit_log(
        session, actor_user_id=user.id, actor_kind="user",
        action="set.url_rip_submitted",
        target_type="rip_job", target_id=str(job.id),
        after={"url": body.url, "platform": job.source_platform},
    )
    await enqueue_rip(session, job, redis_url=_redis_url())

    return _to_out(job)


@router.get("/api/me/rip-jobs", response_model=RipJobsListOut)
async def my_rip_jobs(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
    status: str | None = None,
    limit: int = 50,
):
    q = select(RipJob).where(RipJob.submitted_by == user.id)
    if status == "active":
        q = q.where(RipJob.status.not_in(("ready", "failed")))
    q = q.order_by(RipJob.created_at.desc()).limit(limit)
    rows = (await session.execute(q)).scalars().all()

    set_ids = [r.live_set_id for r in rows if r.live_set_id]
    sets_by_id: dict[uuid.UUID, str] = {}
    if set_ids:
        live_rows = (await session.execute(
            select(LiveSet).where(LiveSet.id.in_(set_ids))
        )).scalars().all()
        sets_by_id = {ls.id: ls.slug for ls in live_rows}

    return RipJobsListOut(items=[
        _to_out(r, live_set_slug=sets_by_id.get(r.live_set_id) if r.live_set_id else None)
        for r in rows
    ])


_TERMINAL_STATUSES = ("ready", "failed")


@router.delete("/api/me/rip-jobs", status_code=204)
async def clear_my_finished_rip_jobs(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    """Clear the caller's finished (ready/failed) rips from their history.
    In-progress jobs are left alone so a running worker job is never orphaned.
    Removes only the RipJob rows — any resulting LiveSet is untouched."""
    await session.execute(
        delete(RipJob).where(
            RipJob.submitted_by == user.id,
            RipJob.status.in_(_TERMINAL_STATUSES),
        )
    )
    await session.commit()


@router.delete("/api/me/rip-jobs/{job_id}", status_code=204)
async def delete_my_rip_job(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    """Remove one of the caller's rips from their history. 404 (not 403) when
    the job is missing or owned by another user, so ids can't be probed."""
    job = await session.get(RipJob, job_id)
    if job is None or job.submitted_by != user.id:
        raise HTTPException(status_code=404, detail="not found")
    await session.delete(job)
    await session.commit()

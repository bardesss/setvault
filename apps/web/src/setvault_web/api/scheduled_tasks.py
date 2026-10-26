"""Admin scheduled-tasks API (§J14).

Lists rq-scheduler jobs (the periodic ones registered in
``apps/worker/src/setvault_worker/entrypoint.py`` plus anything added at
runtime) with next-run + interval + meta, and exposes a Run-now button that
enqueues the job onto its queue immediately. Read-only otherwise —
admins can't add or delete scheduled jobs from the UI for v0.1.0.
"""
from __future__ import annotations

import logging
from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq_scheduler import Scheduler
from setvault_core.config import redis_url
from setvault_core.jobs.upgrade_search import UPGRADE_QUEUE, UPGRADE_SEARCH_JOB_TIMEOUT

from setvault_web.deps import current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/tasks", tags=["admin"])


def _redis() -> Redis:
    return Redis.from_url(redis_url())


# Timeouts for long scheduled jobs whose rq-scheduler entry carries none
# (e.g. registered before the timeout was added). Mirrors the worker's
# _SCHEDULE; without one RQ kills the job after its 180 s default.
_RUN_NOW_TIMEOUTS: dict[str, int] = {
    "setvault_core.jobs.upgrade_search.run_upgrade_search": UPGRADE_SEARCH_JOB_TIMEOUT,
}

# Queues for jobs that don't run on "default" (mirrors the worker's _QUEUES).
_RUN_NOW_QUEUES: dict[str, str] = {
    "setvault_core.jobs.upgrade_search.run_upgrade_search": UPGRADE_QUEUE,
}


def _short_name(func_path: str) -> str:
    """The trailing component of a dotted path. ``rq``-scheduler returns the
    full module path; the UI shows the friendlier name."""
    return func_path.rsplit(".", 1)[-1]


@router.get("")
async def list_scheduled(
    _: Annotated[object, Depends(require_admin)],
):
    """Returns every job rq-scheduler knows about."""
    scheduler = Scheduler(connection=_redis())
    items: list[dict] = []
    for job in scheduler.get_jobs(with_times=True):
        rq_job, next_run = job
        meta = rq_job.meta or {}
        interval = meta.get("interval")
        items.append({
            "id": rq_job.id,
            "func_name": rq_job.func_name,
            "short_name": _short_name(rq_job.func_name),
            "next_run_at": (
                next_run.replace(tzinfo=UTC).isoformat()
                if next_run else None
            ),
            "interval_seconds": int(interval) if interval else None,
            "last_run_at": (
                rq_job.ended_at.replace(tzinfo=UTC).isoformat()
                if rq_job.ended_at else None
            ),
            "last_status": rq_job.get_status() if rq_job else None,
        })
    items.sort(key=lambda d: d["short_name"])
    return {"items": items}


@router.post("/run-now")
async def run_now(
    payload: dict,
    admin: Annotated[object, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    """Enqueue the named function on its queue (default, or low for upgrade
    work) immediately.

    Body: ``{"func_name": "setvault_core.jobs.recycle_bin_purge.run_purge_recycle_bin"}``.
    The function must be one of the registered scheduled funcs — we reject
    arbitrary callable strings so this can't be used as a remote-code-
    execution vector.
    """
    func_path = payload.get("func_name")
    if not func_path or not isinstance(func_path, str):
        raise HTTPException(status_code=400, detail="func_name required")

    scheduler = Scheduler(connection=_redis())
    known = {j.func_name: j for j in scheduler.get_jobs()}
    if func_path not in known:
        raise HTTPException(
            status_code=400,
            detail=f"func_name {func_path!r} is not a registered scheduled job",
        )

    try:
        queue = Queue(_RUN_NOW_QUEUES.get(func_path, "default"), connection=_redis())
        # Same timeout as the scheduled run.
        timeout = known[func_path].timeout or _RUN_NOW_TIMEOUTS.get(func_path)
        rq_job = queue.enqueue(func_path, job_timeout=timeout)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=500, detail="enqueue failed") from exc

    logger.info("admin %s triggered run-now for %s -> %s", admin.id, func_path, rq_job.id)
    return {"status": "queued", "func_name": func_path, "job_id": rq_job.id}

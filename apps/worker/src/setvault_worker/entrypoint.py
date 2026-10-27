"""Worker entrypoint.

Boots an RQ worker (``RecordingWorker``, which records every run for
Admin -> Jobs) on the `default` and `low` queues (in that priority order:
upgrade searches and upgrade rips go on `low`, so they never hold up uploads)
and registers the periodic jobs (e.g. MediaRoot health-checks) with
rq-scheduler. At start it also queues the set size backfill while sets
still lack a recorded size.

Notes on API drift:
  * `rq>=2.0` removed `rq.Connection`; we pass `connection=` directly to
    `Worker` and `Queue` instead.
  * `rq-scheduler.Scheduler.schedule(scheduled_time=..., func=..., interval=...,
    repeat=None)` is the modern signature.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import UTC, datetime

from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler
from setvault_core.db import init_engine
from setvault_core.jobs import size_backfill
from setvault_core.jobs.backup import BACKUP_JOB_TIMEOUT
from setvault_core.jobs.email import SECRET_KEY_ENV
from setvault_core.jobs.upgrade_search import UPGRADE_QUEUE, UPGRADE_SEARCH_JOB_TIMEOUT
from setvault_core.services import webhook_security
from setvault_core.services.crypto import Crypter
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from setvault_worker.recording import RecordingWorker

logger = logging.getLogger(__name__)

# How long boot waits for the size backfill check (DB + Redis) at most.
SIZE_BACKFILL_CHECK_SECONDS = 5.0

_HOURLY = 60 * 60
_DAILY = 24 * 60 * 60

# (func_path, interval_seconds[, job_timeout]). Re-registered exactly once at
# worker boot. Without a timeout RQ's default (180 s) applies; RQ accepts
# seconds or a string like "2h".
_SCHEDULE: tuple[tuple[str, int] | tuple[str, int, int | str], ...] = (
    ("setvault_core.jobs.media_root_health.run_health_checks_sync", 5 * 60),
    ("setvault_core.jobs.recycle_bin_purge.run_purge_recycle_bin", _HOURLY),
    ("setvault_core.jobs.github_version_poll.run_poll_github_releases", _DAILY),
    ("setvault_core.jobs.audit_retention.run_prune_audit_events", _DAILY),
    ("setvault_core.jobs.monitor_dispatch.run_dispatch_monitors", 5 * 60),
    ("setvault_core.jobs.tus_spool_prune.run_prune_tus_spool", _DAILY),
    # Hourly batches spread the daily/weekly upgrade sweep over its window.
    ("setvault_core.jobs.upgrade_search.run_upgrade_search", _HOURLY,
     UPGRADE_SEARCH_JOB_TIMEOUT),
    # Runs the nightly DB backup once it is due (catches up after downtime).
    ("setvault_core.jobs.backup.run_backup_tick", _HOURLY, BACKUP_JOB_TIMEOUT),
)
# Queue per scheduled job when not "default" (R30).
_QUEUES: dict[str, str] = {
    "setvault_core.jobs.upgrade_search.run_upgrade_search": UPGRADE_QUEUE,
}
_QUEUE_ORDER = ("default", UPGRADE_QUEUE)


def _bootstrap_scheduler(redis: Redis) -> None:
    """Register every periodic job exactly once at boot. Existing scheduled
    entries are left in place — rq-scheduler doesn't expose an idempotent
    upsert, so the safest pattern is "only insert if not already present"
    keyed on the func path. An entry registered on another queue than the
    one it belongs on now is replaced."""
    scheduler = Scheduler(connection=redis)
    already = {j.func_name: j for j in scheduler.get_jobs()}
    for func_path, interval, *timeout in _SCHEDULE:
        queue_name = _QUEUES.get(func_path, "default")
        existing = already.get(func_path)
        if existing is not None:
            if existing.origin == queue_name:
                continue
            scheduler.cancel(existing)
        scheduler.schedule(
            scheduled_time=datetime.now(UTC),
            func=func_path,
            interval=interval,
            repeat=None,
            timeout=timeout[0] if timeout else None,
            queue_name=queue_name,
        )


async def _size_backfill_check(database_url: str, redis: Redis) -> bool:
    # An engine of its own (not the process-wide one), so this check can be
    # left running in its thread without touching what the worker uses.
    engine = create_async_engine(
        database_url, poolclass=NullPool,
        connect_args={"timeout": SIZE_BACKFILL_CHECK_SECONDS},
    )
    try:
        async with async_sessionmaker(engine)() as s:
            return await size_backfill.enqueue_if_needed(s, redis=redis)
    finally:
        await engine.dispose()


def _queue_size_backfill(database_url: str, redis: Redis) -> None:
    """Queue the one-off set size backfill while any set lacks a size.

    Best effort, and bounded: the check runs in a daemon thread that boot
    waits on for at most SIZE_BACKFILL_CHECK_SECONDS. A failure is logged;
    a slow DB or Redis never holds up the worker (it is built to keep
    running while the DB is down)."""
    def _run() -> None:
        try:
            if asyncio.run(_size_backfill_check(database_url, redis)):
                logger.info("size backfill queued")
        except Exception:
            logger.exception("queueing the size backfill failed")

    thread = threading.Thread(target=_run, name="size-backfill-check", daemon=True)
    thread.start()
    thread.join(SIZE_BACKFILL_CHECK_SECONDS)
    if thread.is_alive():
        logger.warning("size backfill check still running after %ss; starting the "
                       "worker without waiting for it", SIZE_BACKFILL_CHECK_SECONDS)


async def _migrate_webhook_headers_async(database_url: str, secret_key: str) -> int:
    engine = create_async_engine(
        database_url, poolclass=NullPool,
        connect_args={"timeout": SIZE_BACKFILL_CHECK_SECONDS},
    )
    try:
        async with async_sessionmaker(engine)() as s:
            n = await webhook_security.migrate_plaintext_headers(s, Crypter(secret_key))
            await s.commit()
            return n
    finally:
        await engine.dispose()


def _migrate_webhook_headers(database_url: str, secret_key: str) -> None:
    """Encrypt webhook headers still stored as plaintext. Best effort and
    bounded, like the size backfill: a failure is logged, never fatal."""
    def _run() -> None:
        try:
            n = asyncio.run(_migrate_webhook_headers_async(database_url, secret_key))
            if n:
                logger.info("encrypted the headers of %d webhook(s)", n)
        except Exception:
            logger.exception("migrating the webhook headers failed")

    thread = threading.Thread(target=_run, name="webhook-headers-migrate", daemon=True)
    thread.start()
    thread.join(SIZE_BACKFILL_CHECK_SECONDS)
    if thread.is_alive():
        logger.warning("webhook headers migration still running after %ss; starting "
                       "the worker without waiting for it", SIZE_BACKFILL_CHECK_SECONDS)


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    init_engine(database_url)
    redis = Redis.from_url(os.environ["REDIS_URL"])
    _bootstrap_scheduler(redis)
    _queue_size_backfill(database_url, redis)
    secret_key = os.environ.get(SECRET_KEY_ENV)
    if secret_key:
        _migrate_webhook_headers(database_url, secret_key)
    else:
        logger.warning("SECRET_KEY not set; skipping the webhook headers migration")
    queues = [Queue(name, connection=redis) for name in _QUEUE_ORDER]
    # Records each run in the jobs table (Admin -> Jobs).
    RecordingWorker(queues, connection=redis, database_url=database_url).work(
        with_scheduler=True
    )


if __name__ == "__main__":
    main()

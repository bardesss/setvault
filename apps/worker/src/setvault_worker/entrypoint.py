"""Worker entrypoint.

Boots an RQ worker (``RecordingWorker``, which records every run for
Admin -> Jobs) on the `default` and `low` queues (in that priority order:
upgrade searches and upgrade rips go on `low`, so they never hold up uploads)
and registers the periodic jobs (e.g. MediaRoot health-checks) with
rq-scheduler.

Notes on API drift:
  * `rq>=2.0` removed `rq.Connection`; we pass `connection=` directly to
    `Worker` and `Queue` instead.
  * `rq-scheduler.Scheduler.schedule(scheduled_time=..., func=..., interval=...,
    repeat=None)` is the modern signature.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler
from setvault_core.db import init_engine
from setvault_core.jobs.backup import BACKUP_JOB_TIMEOUT
from setvault_core.jobs.upgrade_search import UPGRADE_QUEUE, UPGRADE_SEARCH_JOB_TIMEOUT

from setvault_worker.recording import RecordingWorker

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


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    init_engine(database_url)
    redis = Redis.from_url(os.environ["REDIS_URL"])
    _bootstrap_scheduler(redis)
    queues = [Queue(name, connection=redis) for name in _QUEUE_ORDER]
    # Records each run in the jobs table (Admin -> Jobs).
    RecordingWorker(queues, connection=redis, database_url=database_url).work(
        with_scheduler=True
    )


if __name__ == "__main__":
    main()

"""What the `scheduler` s6 service does: rq-scheduler's poll moves due entries
from its own Redis key onto each job's queue (`default`, or `low` for upgrade
work; RQ's with_scheduler=True does not serve that key)."""
import os

import pytest
from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler

_REDIS_URL = os.environ.get("TEST_SCHEDULER_REDIS_URL", "redis://localhost:6379/9")


@pytest.fixture
def redis():
    r = Redis.from_url(_REDIS_URL)
    r.flushdb()
    yield r
    r.flushdb()


def test_due_scheduled_job_lands_on_default_queue(redis):
    from setvault_worker.entrypoint import _QUEUES, _SCHEDULE, _bootstrap_scheduler

    _bootstrap_scheduler(redis)
    scheduler = Scheduler(connection=redis)
    assert {j.func_name for j in scheduler.get_jobs()} == {entry[0] for entry in _SCHEDULE}
    queue = Queue("default", connection=redis)
    low = Queue("low", connection=redis)
    assert queue.count == 0  # registering alone enqueues nothing

    scheduler.enqueue_jobs()  # one poll, as `rqscheduler` does each tick

    on_low = {entry[0] for entry in _SCHEDULE if _QUEUES.get(entry[0]) == "low"}
    assert queue.count + low.count == len(_SCHEDULE)
    assert {j.func_name for j in queue.jobs} == {entry[0] for entry in _SCHEDULE} - on_low
    assert {j.func_name for j in low.jobs} == on_low
    # interval jobs stay scheduled for their next run
    assert len(list(scheduler.get_jobs())) == len(_SCHEDULE)


def test_upgrade_search_is_scheduled_on_the_low_queue(redis):
    """R30: upgrade work never starves uploads on the single worker."""
    from setvault_worker.entrypoint import _QUEUES

    assert _QUEUES["setvault_core.jobs.upgrade_search.run_upgrade_search"] == "low"


def test_bootstrap_moves_an_entry_registered_on_the_wrong_queue(redis):
    from setvault_worker.entrypoint import _bootstrap_scheduler

    func = "setvault_core.jobs.upgrade_search.run_upgrade_search"
    from datetime import UTC, datetime
    Scheduler(connection=redis).schedule(
        scheduled_time=datetime.now(UTC), func=func, interval=3600, repeat=None,
    )
    _bootstrap_scheduler(redis)
    jobs = [j for j in Scheduler(connection=redis).get_jobs() if j.func_name == func]
    assert len(jobs) == 1 and jobs[0].origin == "low"


def test_worker_serves_default_before_low(monkeypatch):
    from setvault_worker import entrypoint

    seen = {}

    class FakeWorker:
        def __init__(self, queues, connection):
            seen["queues"] = [q.name for q in queues]

        def work(self, **kw):
            seen["work"] = kw

    monkeypatch.setattr(entrypoint, "Worker", FakeWorker)
    monkeypatch.setattr(entrypoint, "init_engine", lambda url: None)
    monkeypatch.setattr(entrypoint, "_bootstrap_scheduler", lambda redis: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv("REDIS_URL", _REDIS_URL)
    entrypoint.main()
    assert seen["queues"] == ["default", "low"]

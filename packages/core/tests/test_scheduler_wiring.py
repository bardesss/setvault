"""What the `scheduler` s6 service does: rq-scheduler's poll moves due entries
from its own Redis key onto the `default` queue (RQ's with_scheduler=True does
not serve that key)."""
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
    from setvault_worker.entrypoint import _SCHEDULE, _bootstrap_scheduler

    _bootstrap_scheduler(redis)
    scheduler = Scheduler(connection=redis)
    assert {j.func_name for j in scheduler.get_jobs()} == {entry[0] for entry in _SCHEDULE}
    queue = Queue("default", connection=redis)
    assert queue.count == 0  # registering alone enqueues nothing

    scheduler.enqueue_jobs()  # one poll, as `rqscheduler` does each tick

    assert queue.count == len(_SCHEDULE)
    assert {j.func_name for j in queue.jobs} == {entry[0] for entry in _SCHEDULE}
    # interval jobs stay scheduled for their next run
    assert len(list(scheduler.get_jobs())) == len(_SCHEDULE)

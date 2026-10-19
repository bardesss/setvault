"""Admin scheduled-tasks API: "Run now" keeps the scheduled job's timeout."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from setvault_web.api import scheduled_tasks

UPGRADE = "setvault_core.jobs.upgrade_search.run_upgrade_search"
PURGE = "setvault_core.jobs.recycle_bin_purge.run_purge_recycle_bin"


@pytest.fixture
def fake_rq(monkeypatch):
    jobs = [SimpleNamespace(func_name=UPGRADE, timeout=None),
            SimpleNamespace(func_name=PURGE, timeout=None)]
    enqueued: list[tuple[str, dict]] = []

    class FakeScheduler:
        def __init__(self, connection):
            pass

        def get_jobs(self):
            return jobs

    class FakeQueue:
        def __init__(self, name, connection):
            pass

        def enqueue(self, func, **kw):
            enqueued.append((func, kw))
            return SimpleNamespace(id="job-1")

    monkeypatch.setattr(scheduled_tasks, "Scheduler", FakeScheduler)
    monkeypatch.setattr(scheduled_tasks, "Queue", FakeQueue)
    return SimpleNamespace(jobs=jobs, enqueued=enqueued)


@pytest.mark.asyncio
async def test_run_now_of_the_upgrade_search_keeps_its_timeout(authed_admin_client, fake_rq):
    from setvault_core.jobs.upgrade_search import UPGRADE_SEARCH_JOB_TIMEOUT

    # The scheduler entry's own timeout wins.
    fake_rq.jobs[0].timeout = 1234
    r = await authed_admin_client.post("/api/admin/tasks/run-now", json={"func_name": UPGRADE})
    assert r.status_code == 200, r.text
    assert fake_rq.enqueued[-1] == (UPGRADE, {"job_timeout": 1234})

    # An entry registered without one falls back to the known timeout.
    fake_rq.jobs[0].timeout = None
    r = await authed_admin_client.post("/api/admin/tasks/run-now", json={"func_name": UPGRADE})
    assert r.status_code == 200, r.text
    assert fake_rq.enqueued[-1] == (UPGRADE, {"job_timeout": UPGRADE_SEARCH_JOB_TIMEOUT})

    # Short jobs keep RQ's default.
    r = await authed_admin_client.post("/api/admin/tasks/run-now", json={"func_name": PURGE})
    assert r.status_code == 200, r.text
    assert fake_rq.enqueued[-1] == (PURGE, {"job_timeout": None})


@pytest.mark.asyncio
async def test_run_now_rejects_unregistered_funcs(authed_admin_client, fake_rq):
    r = await authed_admin_client.post("/api/admin/tasks/run-now", json={"func_name": "os.system"})
    assert r.status_code == 400
    assert fake_rq.enqueued == []

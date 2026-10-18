import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.jobs import monitor_dispatch as job
from setvault_core.models.identity import User
from setvault_core.models.monitors import Monitor
from setvault_core.services.passwords import hash_password


async def _make_user(session):
    u = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash=hash_password("aaaaaaaa"))
    session.add(u)
    await session.flush()
    return u


@pytest.mark.asyncio
async def test_dispatch_enqueues_only_due_monitors(session, monkeypatch):
    u = await _make_user(session)
    now = datetime.now(UTC)
    due = Monitor(kind="query", query_text="a", owner_user_id=u.id, enabled=True,
                  per_poll_cap=5, last_checked_at=now - timedelta(hours=2))
    fresh = Monitor(kind="query", query_text="b", owner_user_id=u.id, enabled=True,
                    per_poll_cap=5, last_checked_at=now)
    session.add_all([due, fresh])
    await session.flush()

    enqueued = []
    monkeypatch.setattr(job, "_enqueue_poll", lambda mid: enqueued.append(str(mid)))

    count = await job.dispatch_monitors(session, interval_seconds=3600, now=now)
    assert count == 1
    assert str(due.id) in enqueued
    assert str(fresh.id) not in enqueued


def test_enqueue_poll_skips_a_monitor_whose_poll_is_still_in_flight(monkeypatch):
    """A queued-but-not-yet-run poll leaves last_checked_at stale, so the next
    dispatch tick sees the monitor as due again; it must not stack a second
    poll behind the first."""
    import os

    from redis import Redis
    from rq.job import Job

    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set")
    monkeypatch.setenv("REDIS_URL", url)
    redis = Redis.from_url(url)
    monitor_id = uuid.uuid4()
    try:
        assert job._enqueue_poll(monitor_id) is True
        assert job._enqueue_poll(monitor_id) is False   # still queued

        # Once that poll has run, the next tick may enqueue again.
        queued = Job.fetch(job._poll_job_id(monitor_id), connection=redis)
        queued.set_status("finished")
        assert job._enqueue_poll(monitor_id) is True
    finally:
        j = Job.fetch_many([job._poll_job_id(monitor_id)], connection=redis)[0]
        if j is not None:
            j.delete()

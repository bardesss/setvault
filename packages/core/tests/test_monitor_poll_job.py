import os
import uuid

import pytest
from setvault_core.jobs import monitor_poll as job
from setvault_core.models.identity import User
from setvault_core.models.monitors import Monitor
from setvault_core.services import ingest_sources as ingest_svc
from setvault_core.services.passwords import hash_password
from setvault_ingest_sources.base import Candidate


async def _make_user(session):
    u = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash=hash_password("aaaaaaaa"))
    session.add(u)
    await session.flush()
    return u


def _cand(ext_id):
    return Candidate(source_kind="soundcloud", external_id=ext_id, title="t",
                     uploader="u", duration_seconds=1, thumbnail_url=None,
                     webpage_url=f"https://x/{ext_id}")


@pytest.mark.asyncio
async def test_poll_query_monitor_calls_search_all_and_processes(session, monkeypatch):
    u = await _make_user(session)
    m = Monitor(kind="query", query_text="Bicep", owner_user_id=u.id, enabled=True, per_poll_cap=5)
    session.add(m)
    await session.flush()

    async def fake_search_all(s, *, query, limit_per_source=10):
        return ingest_svc.SearchAllResult(candidates=[_cand("a")], errored_kinds=[],
                                         throttled_kinds=[])
    captured = {}
    async def fake_process(s, *, monitor, candidates):
        captured["count"] = len(candidates)
        return {"auto_ingested": 1, "pending_review": 0, "skipped_duplicate": 0}
    monkeypatch.setattr(job, "search_all_sources", fake_search_all)
    monkeypatch.setattr(job, "process_candidates", fake_process)

    summary = await job.poll_monitor(session, monitor_id=m.id)
    assert captured["count"] == 1
    assert summary["auto_ingested"] == 1
    refreshed = await session.get(Monitor, m.id)
    assert refreshed.last_checked_at is not None


@pytest.mark.asyncio
async def test_poll_entity_monitor_calls_single_source(session, monkeypatch):
    u = await _make_user(session)
    m = Monitor(kind="entity", source_kind="soundcloud", external_id="chan1",
                owner_user_id=u.id, enabled=True, per_poll_cap=5)
    session.add(m)
    await session.flush()

    called = {}
    async def fake_search_source(s, *, kind, query, limit=20):
        called["kind"] = kind
        return [_cand("a")]
    async def fake_process(s, *, monitor, candidates):
        return {"auto_ingested": 0, "pending_review": 1, "skipped_duplicate": 0}
    monkeypatch.setattr(job, "search_source", fake_search_source)
    monkeypatch.setattr(job, "process_candidates", fake_process)

    await job.poll_monitor(session, monitor_id=m.id)
    assert called["kind"] == "soundcloud"


@pytest.mark.asyncio
async def test_poll_swallows_rate_limit(session, monkeypatch):
    u = await _make_user(session)
    m = Monitor(kind="query", query_text="x", source_kind="youtube",
                owner_user_id=u.id, enabled=True, per_poll_cap=5)
    session.add(m)
    await session.flush()

    async def boom(s, *, kind, query, limit=20):
        raise ingest_svc.SourceRateLimitedError(kind)
    processed = {}
    async def fake_process(s, *, monitor, candidates):
        processed["count"] = len(candidates)
        return {"auto_ingested": 0, "pending_review": 0, "skipped_duplicate": 0}
    monkeypatch.setattr(job, "search_source", boom)
    monkeypatch.setattr(job, "process_candidates", fake_process)

    await job.poll_monitor(session, monitor_id=m.id)  # must not raise
    assert processed["count"] == 0


@pytest.mark.asyncio
async def test_poll_source_error_persists_failure(session, monkeypatch):
    """A SourceError from a single-source monitor must not roll back the failure
    bookkeeping search_source flushed: a fresh session sees it."""
    from setvault_core.db import init_engine, session_factory
    from setvault_core.models.ingest_sources import IngestSourceState
    from setvault_ingest_sources.base import SourceError
    from sqlalchemy import select

    class _BadSrc:
        kind = "youtube"
        name = "YouTube"

        def search(self, q, *, limit=20):
            raise SourceError("nope")

    monkeypatch.setattr(ingest_svc, "get_source", lambda kind: _BadSrc())
    await ingest_svc.ensure_seed_states(session)
    await ingest_svc.set_enabled(session, "youtube", True)
    st = await ingest_svc.get_state(session, "youtube")
    st.rate_limit_max, st.rate_limit_window_seconds = 1000, 60
    u = await _make_user(session)
    m = Monitor(kind="query", query_text="x", source_kind="youtube",
                owner_user_id=u.id, enabled=True, per_poll_cap=5)
    session.add(m)
    await session.commit()

    init_engine(os.environ["TEST_DATABASE_URL"])
    try:
        await job.poll_monitor(session, monitor_id=m.id)  # must not raise
        async with session_factory()() as fresh:
            st2 = (await fresh.execute(
                select(IngestSourceState).where(IngestSourceState.kind == "youtube")
            )).scalar_one()
            assert st2.consecutive_failures == 1
            assert st2.state == "degraded"
            m2 = await fresh.get(Monitor, m.id)
            assert m2.last_checked_at is not None
    finally:
        async with session_factory()() as fresh:
            st3 = (await fresh.execute(
                select(IngestSourceState).where(IngestSourceState.kind == "youtube")
            )).scalar_one()
            st3.consecutive_failures, st3.state, st3.last_error = 0, "healthy", None
            await fresh.commit()


@pytest.mark.asyncio
async def test_auto_ingest_enqueues_after_poll_commit(session, monkeypatch):
    """The RipJob is committed before it is enqueued (a worker must see the row),
    and the enqueue carries the long rip timeout."""
    from setvault_core.jobs.url_rip_job import RIP_JOB_TIMEOUT
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import rip_enqueue, url_rip

    u = await _make_user(session)
    m = Monitor(kind="entity", source_kind="soundcloud", external_id="chan1",
                owner_user_id=u.id, enabled=True, per_poll_cap=5)
    session.add(m)
    await session.flush()

    async def fake_search_source(s, *, kind, query, limit=20):
        return [_cand("a")]

    async def fake_submit(s, *, user_id, url, **_kw):
        j = RipJob(submitted_by=user_id, source_url=url, status="queued")
        s.add(j)
        await s.flush()
        return j

    seen: list[dict] = []

    class _Q:
        def enqueue(self, *_a, **kw):
            seen.append({**kw, "in_tx": session.in_transaction()})

    monkeypatch.setattr(job, "search_source", fake_search_source)
    monkeypatch.setattr(url_rip, "submit_rip", fake_submit)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: _Q())

    summary = await job.poll_monitor(session, monitor_id=m.id)
    assert summary["auto_ingested"] == 1 and "rip_jobs" not in summary
    (call,) = seen
    assert call["job_timeout"] == RIP_JOB_TIMEOUT
    assert call["in_tx"] is False  # committed before enqueueing

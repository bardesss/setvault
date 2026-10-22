import uuid
from types import SimpleNamespace

import pytest
from setvault_core.models.identity import User
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.services import discoveries as svc
from setvault_core.services.passwords import hash_password
from setvault_ingest_sources.base import Candidate
from sqlalchemy import select


async def _make_user(session):
    u = User(
        email=f"u-{uuid.uuid4().hex[:6]}@x.test",
        username=f"u{uuid.uuid4().hex[:6]}",
        display_name="u",
        password_hash=hash_password("aaaaaaaa"),
    )
    session.add(u)
    await session.flush()
    return u


def _cand(ext_id, title, uploader, kind="soundcloud"):
    return Candidate(
        source_kind=kind,
        external_id=ext_id,
        title=title,
        uploader=uploader,
        duration_seconds=3600,
        thumbnail_url=None,
        webpage_url=f"https://soundcloud.com/x/{ext_id}",
    )


@pytest.mark.asyncio
async def test_process_splits_auto_vs_review_and_caps(session, monkeypatch):
    ripped = []

    async def fake_ingest(s, *, monitor, candidate):
        ripped.append(candidate.external_id)
        return SimpleNamespace(id=None), False

    notified = []

    async def fake_notify(s, *, user_id, monitor, summary):
        notified.append(summary)

    monkeypatch.setattr(svc, "_ingest_candidate", fake_ingest)
    monkeypatch.setattr(svc, "_notify_owner", fake_notify)

    u = await _make_user(session)
    m = Monitor(kind="query", query_text="Bicep", owner_user_id=u.id, enabled=True, per_poll_cap=1)
    session.add(m)
    await session.flush()

    cands = [
        _cand("a", "Bicep at Field Day", "Bicep"),   # high
        _cand("b", "Bicep live", "Bicep"),            # high but over cap -> review
        _cand("c", "Random mix", "DJ Nobody"),        # low -> review
    ]
    summary = await svc.process_candidates(session, monitor=m, candidates=cands)
    assert summary["auto_ingested"] == 1
    assert summary["pending_review"] == 2
    assert ripped == ["a"]
    rows = (
        await session.execute(
            select(MonitorDiscovery).where(MonitorDiscovery.monitor_id == m.id)
        )
    ).scalars().all()
    assert len(rows) == 3
    assert notified and notified[0]["auto_ingested"] == 1


@pytest.mark.asyncio
async def test_process_dedups_existing_discoveries(session, monkeypatch):
    async def _none(*a, **k):
        return None

    monkeypatch.setattr(svc, "_ingest_candidate", _none)
    monkeypatch.setattr(svc, "_notify_owner", _none)

    u = await _make_user(session)
    m = Monitor(kind="query", query_text="Bicep", owner_user_id=u.id, enabled=True, per_poll_cap=5)
    session.add(m)
    await session.flush()
    session.add(
        MonitorDiscovery(
            monitor_id=m.id,
            source_kind="soundcloud",
            external_id="a",
            title="x",
            uploader="Bicep",
            webpage_url="u",
            confidence="high",
            status="auto_ingested",
        )
    )
    await session.flush()

    summary = await svc.process_candidates(
        session, monitor=m, candidates=[_cand("a", "Bicep", "Bicep")]
    )
    assert summary["auto_ingested"] == 0
    assert summary["pending_review"] == 0
    assert summary["skipped_duplicate"] == 1


@pytest.mark.asyncio
async def test_entity_monitor_always_high(session, monkeypatch):
    ripped = []

    async def fake_ingest(s, *, monitor, candidate):
        ripped.append(candidate.external_id)
        return SimpleNamespace(id=None), False

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(svc, "_ingest_candidate", fake_ingest)
    monkeypatch.setattr(svc, "_notify_owner", _none)

    u = await _make_user(session)
    m = Monitor(
        kind="entity",
        source_kind="soundcloud",
        external_id="chan1",
        owner_user_id=u.id,
        enabled=True,
        per_poll_cap=5,
    )
    session.add(m)
    await session.flush()
    # uploader/title don't match any query, but entity monitors are always high -> auto-ingested
    summary = await svc.process_candidates(
        session, monitor=m, candidates=[_cand("z", "anything", "whoever")]
    )
    assert summary["auto_ingested"] == 1
    assert ripped == ["z"]


async def test_auto_ingest_records_the_monitor_trigger(session, monkeypatch):
    """The upgrade history records what found the copy."""
    from rq import Queue
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import url_rip

    user = await _make_user(session)
    seen: list = []

    async def fake_submit(session, *, user_id, url, trigger=None, **_kw):
        seen.append(trigger)
        return RipJob(id=uuid.uuid4(), submitted_by=user_id, source_url=url)

    monkeypatch.setattr(url_rip, "submit_rip", fake_submit)
    monkeypatch.setattr(
        Queue, "enqueue", lambda self, *a, **kw: pytest.fail("no enqueue in the poll"),
    )
    monitor = Monitor(id=uuid.uuid4(), owner_user_id=user.id)
    result = await svc._ingest_candidate(
        session, monitor=monitor, candidate=_cand("x1", "Some Set", "dj"),
    )
    assert seen == ["monitor"]
    assert result is not None and result[1] is True


async def test_failed_submit_becomes_pending_review(session, monkeypatch):
    """A candidate whose submit failed is reviewable, spends no auto budget and
    is not counted as auto-ingested."""
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import url_rip

    async def fake_submit(session, *, user_id, url, **_kw):
        if url.endswith("/bad"):
            raise RuntimeError("probe failed")
        job = RipJob(submitted_by=user_id, source_url=url, status="queued")
        session.add(job)
        await session.flush()
        return job

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(url_rip, "submit_rip", fake_submit)
    monkeypatch.setattr(svc, "_notify_owner", _none)
    u = await _make_user(session)
    m = Monitor(kind="entity", source_kind="soundcloud", external_id="chan",
                owner_user_id=u.id, enabled=True, per_poll_cap=1)
    session.add(m)
    await session.flush()

    # Different durations -> two separate sets, both eligible for auto-ingest.
    bad = _cand("bad", "Set one", "dj")
    good = Candidate("soundcloud", "good", "Other thing", "dj", 900, None,
                     "https://soundcloud.com/x/good")
    summary = await svc.process_candidates(session, monitor=m, candidates=[bad, good])

    assert summary["auto_ingested"] == 1 and summary["pending_review"] == 1
    assert len(summary["rip_jobs"]) == 1
    rows = {
        r.external_id: r for r in (await session.execute(
            select(MonitorDiscovery).where(MonitorDiscovery.monitor_id == m.id)
        )).scalars()
    }
    assert rows["bad"].status == "pending_review" and rows["bad"].url_rip_id is None
    assert rows["good"].status == "auto_ingested" and rows["good"].url_rip_id is not None

from __future__ import annotations

import uuid as uuidmod
from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.asyncio
async def test_submit_url_rip_returns_201(authed_admin_client, monkeypatch):
    """POST /api/sets/url-rip returns the created RipJob row."""
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import url_rip as _service

    async def _fake_submit(session, *, user_id, url):
        job = RipJob(
            submitted_by=user_id, source_url=url,
            source_platform="youtube", source_external_id="dQw4w9WgXcQ",
            status="queued", progress_pct=0,
            probed_metadata={"title": "Stub Title"},
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        return job

    monkeypatch.setattr(_service, "submit_rip", _fake_submit)

    r = await authed_admin_client.post(
        "/api/sets/url-rip",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source_platform"] == "youtube"
    assert body["status"] in ("queued", "failed")  # 'failed' if redis unreachable
    assert body["source_external_id"] == "dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_submit_duplicate_url_returns_409(authed_admin_client, monkeypatch):
    """POST /api/sets/url-rip when a duplicate exists returns 409 with a pointer."""
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import url_rip as _service

    existing_id = uuidmod.uuid4()

    async def _fake_submit(session, *, user_id, url):
        existing = RipJob(
            id=existing_id, submitted_by=user_id, source_url=url,
            source_platform="youtube", source_external_id="dQw4w9WgXcQ",
            status="downloading", progress_pct=20,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        raise _service.DuplicateRipError(existing)

    monkeypatch.setattr(_service, "submit_rip", _fake_submit)

    r = await authed_admin_client.post(
        "/api/sets/url-rip",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    assert r.status_code == 409, r.text
    assert str(existing_id) in r.text


@pytest.mark.asyncio
async def test_submit_url_rip_rate_limit_per_user(authed_admin_client, monkeypatch):
    """6th submission within the hourly window returns 429."""
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import url_rip as _service

    async def _fake_submit(session, *, user_id, url):
        job = RipJob(
            submitted_by=user_id, source_url=url,
            source_platform="youtube", source_external_id=f"id-{uuidmod.uuid4().hex[:6]}",
            status="queued", progress_pct=0,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        return job

    monkeypatch.setattr(_service, "submit_rip", _fake_submit)

    for _ in range(5):
        r = await authed_admin_client.post(
            "/api/sets/url-rip",
            json={"url": f"https://www.youtube.com/watch?v={uuidmod.uuid4().hex[:11]}"},
        )
        assert r.status_code == 201, r.text

    r = await authed_admin_client.post(
        "/api/sets/url-rip",
        json={"url": f"https://www.youtube.com/watch?v={uuidmod.uuid4().hex[:11]}"},
    )
    assert r.status_code == 429, r.text


@pytest.mark.asyncio
async def test_my_rip_jobs_lists_recent(authed_admin_client, seeded_admin):
    """GET /api/me/rip-jobs returns the user's recent rip jobs newest-first."""
    from setvault_core.db import session_factory
    from setvault_core.models.url_rip import RipJob

    async with session_factory()() as s:
        for i in range(3):
            s.add(RipJob(
                submitted_by=seeded_admin.id,
                source_url=f"https://x/{i}",
                status="ready",
                progress_pct=100,
                created_at=datetime.now(UTC) - timedelta(minutes=i),
                updated_at=datetime.now(UTC) - timedelta(minutes=i),
            ))
        await s.commit()

    r = await authed_admin_client.get("/api/me/rip-jobs")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 3


@pytest.mark.asyncio
async def test_submit_url_rip_enqueues_with_long_timeout(authed_admin_client, monkeypatch):
    """RQ's 180s default kills a real-length rip; the enqueue must override it."""
    from setvault_core.jobs.url_rip_job import RIP_JOB_TIMEOUT
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import url_rip as _service
    from setvault_web.api import url_rip as url_rip_api

    async def _fake_submit(session, *, user_id, url):
        job = RipJob(
            submitted_by=user_id, source_url=url,
            source_platform="youtube", source_external_id=uuidmod.uuid4().hex[:11],
            status="queued", progress_pct=0, probed_metadata={"title": "t"},
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        return job

    calls: list[dict] = []

    class _Q:
        def enqueue(self, *_args, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(_service, "submit_rip", _fake_submit)
    monkeypatch.setattr(url_rip_api, "_queue", lambda: _Q())

    r = await authed_admin_client.post(
        "/api/sets/url-rip",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    assert r.status_code == 201, r.text
    assert calls[0]["job_timeout"] == RIP_JOB_TIMEOUT

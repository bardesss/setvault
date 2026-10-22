import os
import uuid

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.identity import User
from setvault_core.services.passwords import hash_password


@pytest.mark.asyncio
async def test_admin_can_create_and_list_monitor(authed_admin_client):
    r = await authed_admin_client.post(
        "/api/monitors", json={"kind": "query", "query_text": "Bicep"}
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r = await authed_admin_client.get("/api/monitors")
    assert r.status_code == 200, r.text
    assert any(m["id"] == mid for m in r.json()["items"])


@pytest.mark.asyncio
async def test_delete_monitor(authed_admin_client):
    r = await authed_admin_client.post(
        "/api/monitors", json={"kind": "query", "query_text": "y"}
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r = await authed_admin_client.delete(f"/api/monitors/{mid}")
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_non_admin_blocked_when_setting_off(client):
    # Seed a NON-admin user (default monitors_allow_all_users is False).
    init_engine(os.environ["TEST_DATABASE_URL"])
    email = f"u-{uuid.uuid4().hex[:6]}@x.test"
    password = "hunter2hunter2"
    async with session_factory()() as s:
        u = User(
            email=email,
            username=f"u{uuid.uuid4().hex[:6]}",
            display_name="u",
            password_hash=hash_password(password),
            role="user",
        )
        s.add(u)
        await s.commit()

    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]

    r = await client.post("/api/monitors", json={"kind": "query", "query_text": "x"})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_non_admin_cannot_access_other_users_monitors(client):
    """In all-users mode, a non-admin must not see/mutate another user's
    monitors (IDOR guard). Admins are unrestricted; that's covered elsewhere."""
    from setvault_core.services.system_config import get_config

    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        cfg = await get_config(s)
        cfg.monitors_allow_all_users = True
        await s.commit()

    try:
        async def _seed_user():
            email = f"u-{uuid.uuid4().hex[:6]}@x.test"
            pw = "hunter2hunter2"
            async with session_factory()() as s:
                s.add(User(
                    email=email, username=f"u{uuid.uuid4().hex[:6]}", display_name="u",
                    password_hash=hash_password(pw), role="user",
                ))
                await s.commit()
            return email, pw

        async def _login(email, pw):
            r = await client.post(
                "/api/auth/login", json={"email": email, "password": pw}
            )
            assert r.status_code == 200, r.text
            client.cookies = r.cookies
            client.headers["X-CSRF-Token"] = r.cookies["csrf_token"]

        a_email, a_pw = await _seed_user()
        b_email, b_pw = await _seed_user()

        await _login(a_email, a_pw)
        r = await client.post(
            "/api/monitors", json={"kind": "query", "query_text": "AonlyQ"}
        )
        assert r.status_code == 201, r.text
        a_mid = r.json()["id"]

        # User B must not see, update, or delete A's monitor.
        await _login(b_email, b_pw)
        r = await client.get("/api/monitors")
        assert r.status_code == 200, r.text
        assert all(m["id"] != a_mid for m in r.json()["items"])

        r = await client.put(f"/api/monitors/{a_mid}", json={"enabled": False})
        assert r.status_code == 404, r.text

        r = await client.delete(f"/api/monitors/{a_mid}")
        assert r.status_code == 404, r.text
    finally:
        async with session_factory()() as s:
            cfg = await get_config(s)
            cfg.monitors_allow_all_users = False
            await s.commit()


@pytest.mark.asyncio
async def test_rip_discovery_marks_job_failed_when_enqueue_fails(authed_admin_client, monkeypatch):
    """A queue outage while accepting a discovery must leave a visible, retryable
    failed RipJob (like POST /api/url-rip), not one stuck at "queued" forever."""
    from setvault_core.models.monitors import MonitorDiscovery
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import rip_enqueue
    from setvault_web.api import monitors as monitors_api

    r = await authed_admin_client.post("/api/monitors", json={"kind": "query", "query_text": "q"})
    assert r.status_code == 201, r.text
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        d = MonitorDiscovery(
            monitor_id=uuid.UUID(r.json()["id"]), source_kind="youtube",
            external_id=uuid.uuid4().hex, title="t", webpage_url="https://example.test/v",
            confidence="low", status="pending_review",
        )
        s.add(d)
        await s.commit()
        discovery_id = d.id

    triggers = []

    async def fake_submit(session, *, user_id, url, trigger=None):
        triggers.append(trigger)
        job = RipJob(submitted_by=user_id, source_url=url, status="queued")
        session.add(job)
        await session.flush()
        return job

    class DownQueue:
        def __init__(self, *_a, **_kw):
            pass

        def enqueue(self, *_a, **_kw):
            raise ConnectionError("redis down")

    monkeypatch.setattr(monitors_api, "submit_rip", fake_submit)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: DownQueue())

    r = await authed_admin_client.post(f"/api/me/discoveries/{discovery_id}/rip")
    assert r.status_code == 204, r.text

    async with session_factory()() as s:
        d = await s.get(MonitorDiscovery, discovery_id)
        job = await s.get(RipJob, d.url_rip_id)
        assert job.status == "failed"
        assert job.error_text == "failed to enqueue worker"
    # A manually approved discovery is still a monitor find.
    assert triggers == ["monitor"]


async def _seed_discovery(client) -> uuid.UUID:
    from setvault_core.models.monitors import MonitorDiscovery

    r = await client.post("/api/monitors", json={"kind": "query", "query_text": "q"})
    assert r.status_code == 201, r.text
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        d = MonitorDiscovery(
            monitor_id=uuid.UUID(r.json()["id"]), source_kind="youtube",
            external_id=uuid.uuid4().hex, title="t", webpage_url="https://example.test/v",
            confidence="low", status="pending_review",
        )
        s.add(d)
        await s.commit()
        return d.id


async def _fake_submit(session, *, user_id, url, trigger=None):
    from setvault_core.models.url_rip import RipJob

    job = RipJob(submitted_by=user_id, source_url=url, status="queued")
    session.add(job)
    await session.flush()
    return job


@pytest.mark.asyncio
async def test_rip_discovery_commits_before_enqueue_with_timeout(authed_admin_client, monkeypatch):
    """A worker that pops the job at once must find the RipJob row, and the
    enqueue must override RQ's 180 s default timeout."""
    import asyncio
    import threading

    from setvault_core.jobs.url_rip_job import RIP_JOB_TIMEOUT
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import rip_enqueue
    from setvault_web.api import monitors as monitors_api
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    discovery_id = await _seed_discovery(authed_admin_client)

    def _row_visible_elsewhere(job_id: str) -> bool:
        async def _check() -> bool:
            engine = create_async_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool)
            try:
                async with engine.connect() as conn:
                    row = (await conn.execute(
                        select(RipJob.id).where(RipJob.id == uuid.UUID(job_id)),
                    )).first()
                    return row is not None
            finally:
                await engine.dispose()

        result: list[bool] = []
        t = threading.Thread(target=lambda: result.append(asyncio.run(_check())))
        t.start()
        t.join()
        return result[0]

    seen: list[tuple[bool, object]] = []

    class _Q:
        def enqueue(self, *_a, **kw):
            seen.append((_row_visible_elsewhere(kw["rip_job_id"]), kw.get("job_timeout")))

    monkeypatch.setattr(monitors_api, "submit_rip", _fake_submit)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: _Q())

    r = await authed_admin_client.post(f"/api/me/discoveries/{discovery_id}/rip")
    assert r.status_code == 204, r.text
    assert seen == [(True, RIP_JOB_TIMEOUT)]


@pytest.mark.asyncio
async def test_rip_discovery_status_ingested_only_after_enqueue(authed_admin_client, monkeypatch):
    from setvault_core.models.monitors import MonitorDiscovery
    from setvault_core.services import rip_enqueue
    from setvault_web.api import monitors as monitors_api

    class _Down:
        def enqueue(self, *_a, **_kw):
            raise ConnectionError("redis down")

    class _Up:
        def enqueue(self, *_a, **_kw):
            return None

    monkeypatch.setattr(monitors_api, "submit_rip", _fake_submit)

    down_id = await _seed_discovery(authed_admin_client)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: _Down())
    r = await authed_admin_client.post(f"/api/me/discoveries/{down_id}/rip")
    assert r.status_code == 204, r.text
    async with session_factory()() as s:
        d = await s.get(MonitorDiscovery, down_id)
        assert d.status == "pending_review" and d.decided_at is None

    up_id = await _seed_discovery(authed_admin_client)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: _Up())
    r = await authed_admin_client.post(f"/api/me/discoveries/{up_id}/rip")
    assert r.status_code == 204, r.text
    async with session_factory()() as s:
        d = await s.get(MonitorDiscovery, up_id)
        assert d.status == "ingested" and d.decided_at is not None

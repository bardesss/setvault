import os
import uuid
from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_rip_discovery_probe_failure_returns_400(authed_admin_client, monkeypatch):
    """A URL yt-dlp can't probe is a 400 with the reason, and the discovery
    stays pending_review so it can be tried again later."""
    from setvault_core.models.monitors import MonitorDiscovery
    from setvault_core.services.url_rip import ProbeError
    from setvault_web.api import monitors as monitors_api

    async def _failing_submit(session, *, user_id, url, trigger=None):
        raise ProbeError("[youtube] abc: Sign in to confirm you're not a bot.")

    monkeypatch.setattr(monitors_api, "submit_rip", _failing_submit)
    discovery_id = await _seed_discovery(authed_admin_client)

    r = await authed_admin_client.post(f"/api/me/discoveries/{discovery_id}/rip")
    assert r.status_code == 400, r.text
    assert "not a bot" in r.json()["detail"]
    async with session_factory()() as s:
        d = await s.get(MonitorDiscovery, discovery_id)
        assert d.status == "pending_review" and d.url_rip_id is None


async def _artist(client, name: str = "Linkable") -> dict:
    r = await client.post("/api/catalog/artists", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _linked(artist: dict, **extra) -> dict:
    return {"kind": "query", "query_text": artist["name"], "catalog_kind": "artist",
            "catalog_id": artist["id"], **extra}


@pytest.mark.asyncio
async def test_create_catalog_linked_monitor(authed_admin_client):
    artist = await _artist(authed_admin_client)
    r = await authed_admin_client.post("/api/monitors", json=_linked(artist))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["catalog_kind"] == "artist"
    assert body["catalog_id"] == artist["id"]
    assert body["catalog_name"] == artist["name"]
    assert body["catalog_slug"] == artist["slug"]

    r = await authed_admin_client.get("/api/monitors")
    listed = next(m for m in r.json()["items"] if m["id"] == body["id"])
    assert listed["catalog_name"] == artist["name"]
    assert listed["catalog_slug"] == artist["slug"]

    # Unlinked monitors carry nulls.
    r = await authed_admin_client.post("/api/monitors", json={"kind": "query", "query_text": "x"})
    assert r.status_code == 201, r.text
    assert r.json()["catalog_kind"] is None
    assert r.json()["catalog_name"] is None


@pytest.mark.asyncio
async def test_catalog_link_requires_both_fields_422(authed_admin_client):
    artist = await _artist(authed_admin_client)
    r = await authed_admin_client.post(
        "/api/monitors", json={"kind": "query", "query_text": "x", "catalog_kind": "artist"})
    assert r.status_code == 422, r.text
    r = await authed_admin_client.post(
        "/api/monitors", json={"kind": "query", "query_text": "x", "catalog_id": artist["id"]})
    assert r.status_code == 422, r.text
    r = await authed_admin_client.post(
        "/api/monitors", json=_linked(artist, catalog_kind="series"))
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_catalog_link_unknown_malformed_or_merged_entity_422(authed_admin_client):
    artist = await _artist(authed_admin_client)
    for bad in ("not-a-uuid", str(uuid.uuid4())):
        r = await authed_admin_client.post(
            "/api/monitors", json=_linked(artist, catalog_id=bad))
        assert r.status_code == 422, r.text
    # A party id is not an artist.
    r = await authed_admin_client.post("/api/catalog/parties", json={"name": "P"})
    assert r.status_code == 201, r.text
    r = await authed_admin_client.post(
        "/api/monitors", json=_linked(artist, catalog_id=r.json()["id"]))
    assert r.status_code == 422, r.text

    survivor = await _artist(authed_admin_client, "Survivor")
    r = await authed_admin_client.post(
        f"/api/catalog/artists/{artist['id']}/merge", json={"survivor_id": survivor["id"]})
    assert r.status_code == 200, r.text
    r = await authed_admin_client.post("/api/monitors", json=_linked(artist))
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_catalog_link_on_entity_kind_422(authed_admin_client):
    artist = await _artist(authed_admin_client)
    r = await authed_admin_client.post("/api/monitors", json={
        "kind": "entity", "source_kind": "youtube", "external_id": "UCx",
        "catalog_kind": "artist", "catalog_id": artist["id"],
    })
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_duplicate_catalog_monitor_reenables_existing(authed_admin_client):
    artist = await _artist(authed_admin_client)
    r = await authed_admin_client.post("/api/monitors", json=_linked(artist))
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r = await authed_admin_client.put(
        f"/api/monitors/{mid}", json={"enabled": False, "query_text": "tuned"})
    assert r.status_code == 200, r.text

    r = await authed_admin_client.post("/api/monitors", json=_linked(artist))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == mid
    assert r.json()["enabled"] is True
    assert r.json()["query_text"] == "tuned"  # the user's tuning survives
    r = await authed_admin_client.get("/api/monitors")
    assert [m["id"] for m in r.json()["items"] if m["catalog_id"] == artist["id"]] == [mid]


@pytest.mark.asyncio
async def test_put_edits_query_source_cap(authed_admin_client):
    r = await authed_admin_client.post("/api/monitors", json={"kind": "query", "query_text": "a"})
    mid = r.json()["id"]
    r = await authed_admin_client.put(f"/api/monitors/{mid}", json={
        "query_text": "  new query ", "source_kind": "youtube", "per_poll_cap": 12,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["query_text"], body["source_kind"], body["per_poll_cap"]) == (
        "new query", "youtube", 12)
    assert body["enabled"] is True and body["kind"] == "query"

    # source_kind null means all sources again; kind is not editable.
    r = await authed_admin_client.put(
        f"/api/monitors/{mid}", json={"source_kind": None, "kind": "entity"})
    assert r.status_code == 200, r.text
    assert r.json()["source_kind"] is None and r.json()["kind"] == "query"

    # A query monitor can't lose its query.
    r = await authed_admin_client.put(f"/api/monitors/{mid}", json={"query_text": "  "})
    assert r.status_code == 422, r.text
    r = await authed_admin_client.put(f"/api/monitors/{mid}", json={"enabled": None})
    assert r.status_code == 422, r.text
    r = await authed_admin_client.put(f"/api/monitors/{uuid.uuid4()}", json={"enabled": True})
    assert r.status_code == 404, r.text
    r = await authed_admin_client.put("/api/monitors/nope", json={"enabled": True})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_put_cap_out_of_range_422(authed_admin_client):
    r = await authed_admin_client.post("/api/monitors", json={"kind": "query", "query_text": "a"})
    mid = r.json()["id"]
    for cap in (0, 51):
        r = await authed_admin_client.put(f"/api/monitors/{mid}", json={"per_poll_cap": cap})
        assert r.status_code == 422, r.text
        r = await authed_admin_client.post(
            "/api/monitors", json={"kind": "query", "query_text": "a", "per_poll_cap": cap})
        assert r.status_code == 422, r.text
    for cap in (1, 50):
        r = await authed_admin_client.put(f"/api/monitors/{mid}", json={"per_poll_cap": cap})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_monitor_audit_rows(authed_admin_client):
    from setvault_core.models.system import AuditEvent
    from sqlalchemy import select

    r = await authed_admin_client.post("/api/monitors", json={"kind": "query", "query_text": "a"})
    mid = r.json()["id"]
    r = await authed_admin_client.put(
        f"/api/monitors/{mid}", json={"per_poll_cap": 7, "query_text": "a"})
    assert r.status_code == 200, r.text
    r = await authed_admin_client.delete(f"/api/monitors/{mid}")
    assert r.status_code == 204, r.text

    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        rows = (await s.execute(
            select(AuditEvent).where(AuditEvent.target_id == mid)
        )).scalars().all()
    by_action = {e.action: e for e in rows}
    assert len(rows) == 3
    assert set(by_action) == {"monitor.created", "monitor.edited", "monitor.deleted"}
    assert by_action["monitor.created"].after["query_text"] == "a"
    # Only the changed field: query_text was resent unchanged.
    assert by_action["monitor.edited"].before == {"per_poll_cap": 5}
    assert by_action["monitor.edited"].after == {"per_poll_cap": 7}
    assert by_action["monitor.deleted"].before["query_text"] == "a"
    assert all(e.target_type == "Monitor" for e in rows)


@pytest.mark.asyncio
async def test_discoveries_pending_count(authed_admin_client):
    from setvault_core.models.monitors import MonitorDiscovery

    r = await authed_admin_client.post("/api/monitors", json={"kind": "query", "query_text": "q"})
    mid = uuid.UUID(r.json()["id"])
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        for status in ("pending_review", "pending_review", "dismissed", "auto_ingested"):
            s.add(MonitorDiscovery(
                monitor_id=mid, source_kind="youtube", external_id=uuid.uuid4().hex,
                title="t", webpage_url="https://example.test/v", confidence="low",
                status=status,
            ))
        await s.commit()

    r = await authed_admin_client.get("/api/me/discoveries", params={"status": "dismissed"})
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 1
    assert r.json()["pending_count"] == 2
    r = await authed_admin_client.get("/api/me/discoveries")
    assert len(r.json()["items"]) == 4
    assert r.json()["pending_count"] == 2


@pytest.mark.asyncio
async def test_discoveries_repeated_status_filter(authed_admin_client):
    from setvault_core.models.monitors import MonitorDiscovery

    r = await authed_admin_client.post("/api/monitors", json={"kind": "query", "query_text": "q"})
    mid = uuid.UUID(r.json()["id"])
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        for status in ("ingested", "auto_ingested", "dismissed", "pending_review"):
            s.add(MonitorDiscovery(
                monitor_id=mid, source_kind="youtube", external_id=uuid.uuid4().hex,
                title="t", webpage_url="https://example.test/v", confidence="low",
                status=status,
            ))
        await s.commit()

    r = await authed_admin_client.get(
        "/api/me/discoveries", params=[("status", "ingested"), ("status", "auto_ingested")],
    )
    assert r.status_code == 200, r.text
    assert {d["status"] for d in r.json()["items"]} == {"ingested", "auto_ingested"}
    r = await authed_admin_client.get("/api/me/discoveries", params={"status": "dismissed"})
    assert [d["status"] for d in r.json()["items"]] == ["dismissed"]


class _UpQueue:
    def enqueue(self, *_a, **_kw):
        return None


@pytest.mark.asyncio
async def test_discovery_rip_rate_limited(authed_admin_client, monkeypatch):
    """Manual discovery rips share the URL-rip per-user limit."""
    from setvault_core.services import rip_enqueue
    from setvault_web import rip_limits
    from setvault_web.api import monitors as monitors_api

    monkeypatch.setattr(rip_limits, "RIP_HOURLY_LIMIT", 1)
    # One hourly bucket for both rips, even if the test crosses the hour.
    monkeypatch.setattr("setvault_web.rate_limit.time", SimpleNamespace(time=lambda: 1_000_000.0))
    monkeypatch.setattr(monitors_api, "submit_rip", _fake_submit)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: _UpQueue())

    first = await _seed_discovery(authed_admin_client)
    r = await authed_admin_client.post(f"/api/me/discoveries/{first}/rip")
    assert r.status_code == 204, r.text

    second = await _seed_discovery(authed_admin_client)
    r = await authed_admin_client.post(f"/api/me/discoveries/{second}/rip")
    assert r.status_code == 429, r.text
    assert r.headers["Retry-After"] == "3600"


@pytest.mark.asyncio
async def test_discovery_rip_audited(authed_admin_client, monkeypatch):
    from setvault_core.models.monitors import MonitorDiscovery
    from setvault_core.models.system import AuditEvent
    from setvault_core.services import rip_enqueue
    from setvault_web.api import monitors as monitors_api
    from sqlalchemy import select

    monkeypatch.setattr(monitors_api, "submit_rip", _fake_submit)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: _UpQueue())

    discovery_id = await _seed_discovery(authed_admin_client)
    r = await authed_admin_client.post(f"/api/me/discoveries/{discovery_id}/rip")
    assert r.status_code == 204, r.text

    async with session_factory()() as s:
        d = await s.get(MonitorDiscovery, discovery_id)
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test")
        )).scalar_one()
        rows = (await s.execute(
            select(AuditEvent).where(AuditEvent.action == "set.discovery_rip_submitted",
                                     AuditEvent.target_id == str(d.url_rip_id))
        )).scalars().all()
    assert len(rows) == 1
    ev = rows[0]
    assert ev.actor_user_id == admin.id
    assert ev.target_type == "rip_job"
    assert ev.after == {"discovery_id": str(discovery_id), "url": "https://example.test/v"}


@pytest.mark.asyncio
async def test_admin_rips_others_discovery_as_owner(authed_admin_client, monkeypatch):
    """An admin accepting another user's discovery submits the rip as the
    monitor's owner (like the auto path); the rate limit counts the admin."""
    from setvault_core.models.monitors import Monitor, MonitorDiscovery
    from setvault_core.models.system import AuditEvent
    from setvault_core.models.url_rip import RipJob
    from setvault_core.services import rip_enqueue
    from setvault_web import rip_limits
    from setvault_web.api import monitors as monitors_api
    from sqlalchemy import select

    limited: list[uuid.UUID] = []
    real_enforce = rip_limits.enforce_rip_rate_limit

    async def _spy(user_id):
        limited.append(user_id)
        await real_enforce(user_id)

    monkeypatch.setattr(monitors_api, "enforce_rip_rate_limit", _spy)
    monkeypatch.setattr(monitors_api, "submit_rip", _fake_submit)
    monkeypatch.setattr(rip_enqueue, "_queue", lambda url=None: _UpQueue())

    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        owner = User(
            email=f"u-{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
            display_name="u", password_hash=hash_password("hunter2hunter2"), role="user",
        )
        s.add(owner)
        await s.flush()
        m = Monitor(kind="query", query_text="q", owner_user_id=owner.id)
        s.add(m)
        await s.flush()
        d = MonitorDiscovery(
            monitor_id=m.id, source_kind="youtube", external_id=uuid.uuid4().hex,
            title="t", webpage_url="https://example.test/v", confidence="low",
            status="pending_review",
        )
        s.add(d)
        await s.commit()
        owner_id, discovery_id = owner.id, d.id

    r = await authed_admin_client.post(f"/api/me/discoveries/{discovery_id}/rip")
    assert r.status_code == 204, r.text

    async with session_factory()() as s:
        d = await s.get(MonitorDiscovery, discovery_id)
        job = await s.get(RipJob, d.url_rip_id)
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test")
        )).scalar_one()
    assert job.submitted_by == owner_id
    assert limited == [admin.id]
    async with session_factory()() as s:
        audit = (await s.execute(
            select(AuditEvent).where(AuditEvent.action == "set.discovery_rip_submitted")
        )).scalar_one()
    assert audit.actor_user_id == admin.id

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.engagement import ActivityEvent
from setvault_core.models.identity import User
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.models.system import Job
from setvault_core.services.passwords import hash_password
from sqlalchemy import delete, select

NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
async def _clean_activity():
    init_engine(os.environ["TEST_DATABASE_URL"])

    async def wipe():
        async with session_factory()() as s:
            await s.execute(delete(ActivityEvent))
            await s.execute(delete(Job))
            await s.commit()

    await wipe()
    yield
    await wipe()


async def _admin_id() -> uuid.UUID:
    async with session_factory()() as s:
        return (
            await s.execute(select(User.id).where(User.email == "admin@example.test"))
        ).scalar_one()


async def _event(set_id: uuid.UUID, at: datetime, user_id: uuid.UUID | None = None):
    async with session_factory()() as s:
        s.add(ActivityEvent(
            kind="set.published", subject_type="live_set", subject_id=set_id,
            user_id=user_id, payload={}, created_at=at,
        ))
        await s.commit()


async def _discovery(owner: uuid.UUID, title: str, at: datetime, status="pending_review"):
    async with session_factory()() as s:
        m = Monitor(kind="query", query_text="q", owner_user_id=owner)
        s.add(m)
        await s.flush()
        s.add(MonitorDiscovery(
            monitor_id=m.id, source_kind="youtube", external_id=uuid.uuid4().hex[:8],
            title=title, webpage_url="https://x.test/v", confidence="high",
            status=status, created_at=at,
        ))
        await s.commit()


async def _job(kind: str, finished: datetime, status="failed"):
    async with session_factory()() as s:
        s.add(Job(
            rq_id=uuid.uuid4().hex, kind=kind, status=status,
            created_at=finished, finished_at=finished,
        ))
        await s.commit()


async def test_requires_login(client):
    assert (await client.get("/api/me/home-activity")).status_code == 401


async def test_activity_merges_and_orders(authed_admin_client, seeded_live_set):
    admin = await _admin_id()
    await _event(uuid.UUID(seeded_live_set["id"]), NOW - timedelta(hours=3), admin)
    await _discovery(admin, "found one", NOW - timedelta(hours=1))
    await _job("rip", NOW - timedelta(hours=2))
    r = await authed_admin_client.get("/api/me/home-activity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(i["kind"], i["title"], i["href"]) for i in body] == [
        ("discovery", "found one", "/discoveries"),
        ("job_failed", "rip", "/admin/jobs"),
        ("set_published", "seeded set", f"/sets/{seeded_live_set['slug']}"),
    ]


async def test_activity_limit_10(authed_admin_client, seeded_live_set):
    admin = await _admin_id()
    for n in range(12):
        await _event(uuid.UUID(seeded_live_set["id"]), NOW - timedelta(minutes=n))
    for n in range(12):
        await _discovery(admin, f"d{n}", NOW - timedelta(minutes=30 + n))
    r = await authed_admin_client.get("/api/me/home-activity")
    body = r.json()
    assert len(body) == 10
    assert all(i["kind"] == "set_published" for i in body)


async def test_activity_skips_deleted_set(authed_admin_client, seeded_live_set):
    set_id = uuid.UUID(seeded_live_set["id"])
    await _event(set_id, NOW)
    # Soft-deleted set, and an event whose set was hard-deleted.
    async with session_factory()() as s:
        (await s.get(LiveSet, set_id)).deleted_at = NOW
        await s.commit()
    await _event(uuid.uuid4(), NOW)
    r = await authed_admin_client.get("/api/me/home-activity")
    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_non_admin_sees_no_failed_jobs_and_only_own_discoveries(client, seeded_admin):
    admin = seeded_admin.id
    async with session_factory()() as s:
        member = User(
            email=f"m-{uuid.uuid4().hex[:6]}@x.test", username=f"m{uuid.uuid4().hex[:6]}",
            display_name="m", password_hash=hash_password("hunter2hunter2"), role="user",
        )
        s.add(member)
        await s.commit()
        member_id, email = member.id, member.email
    await _discovery(member_id, "mine", NOW - timedelta(hours=1))
    await _discovery(admin, "theirs", NOW - timedelta(hours=2))
    await _job("rip", NOW)
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "hunter2hunter2"}
    )
    client.cookies = login.cookies
    r = await client.get("/api/me/home-activity")
    assert r.status_code == 200, r.text
    assert [(i["kind"], i["title"]) for i in r.json()] == [("discovery", "mine")]
    async with session_factory()() as s:
        await s.execute(delete(Monitor).where(Monitor.owner_user_id == member_id))
        await s.execute(delete(User).where(User.id == member_id))
        await s.commit()


async def test_old_failed_job_excluded(authed_admin_client):
    await _job("old", NOW - timedelta(days=8))
    await _job("recent", NOW - timedelta(days=6))
    await _job("fine", NOW, status="succeeded")
    r = await authed_admin_client.get("/api/me/home-activity")
    assert [i["title"] for i in r.json()] == ["recent"]


async def test_same_timestamp_discoveries_have_distinct_ids(authed_admin_client):
    admin = await _admin_id()
    at = NOW - timedelta(hours=1)
    await _discovery(admin, "twin a", at)
    await _discovery(admin, "twin b", at)
    r = await authed_admin_client.get("/api/me/home-activity")
    body = r.json()
    assert sorted(i["title"] for i in body) == ["twin a", "twin b"]
    assert len({i["id"] for i in body}) == 2
    assert all(i["id"].startswith("discovery:") for i in body)

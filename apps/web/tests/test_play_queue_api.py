import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.services.passwords import hash_password
from sqlalchemy import select


async def _more_sets(seeded_live_set, n: int) -> list[str]:
    slugs = []
    async with session_factory()() as s:
        src = (await s.execute(
            select(LiveSet).where(LiveSet.slug == seeded_live_set["slug"])
        )).scalar_one()
        for i in range(n):
            ls = LiveSet(
                slug=f"q-{uuid.uuid4().hex[:8]}", title=f"q {i}",
                media_root_id=src.media_root_id, audio_path=f"originals/seed/q{i}.flac",
                status="published", source_type="upload", uploaded_by=src.uploaded_by,
            )
            s.add(ls)
            slugs.append(ls.slug)
        await s.commit()
    return slugs


async def _set_state(slug: str, **fields) -> None:
    async with session_factory()() as s:
        ls = (await s.execute(select(LiveSet).where(LiveSet.slug == slug))).scalar_one()
        for k, v in fields.items():
            setattr(ls, k, v)
        await s.commit()


def _body(slugs, index=0, base=None):
    return {"slugs": slugs, "index": index, "base_updated_at": base}


@pytest.mark.asyncio
async def test_empty_queue(authed_admin_client):
    r = await authed_admin_client.get("/api/me/queue")
    assert r.status_code == 200
    assert r.json() == {"slugs": [], "index": 0, "updated_at": None}


@pytest.mark.asyncio
async def test_put_then_get(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    b, d = await _more_sets(seeded_live_set, 2)
    r = await c.put("/api/me/queue", json=_body([a, b, d], 1))
    assert r.status_code == 200, r.text
    assert r.json()["overwrote_newer"] is False
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [a, b, d]
    assert got["index"] == 1
    # the client echoes this string back as base_updated_at, so it must be exact
    assert got["updated_at"] == r.json()["updated_at"]


@pytest.mark.asyncio
async def test_overwrote_newer_reported(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    (b,) = await _more_sets(seeded_live_set, 1)
    first = (await c.put("/api/me/queue", json=_body([a]))).json()
    # based on what we just wrote: not newer
    second = (await c.put("/api/me/queue", json=_body([a, b], 0, first["updated_at"]))).json()
    assert second["overwrote_newer"] is False
    # another tab still holds `first`; the stored queue has moved on
    third = (await c.put("/api/me/queue", json=_body([b], 0, first["updated_at"]))).json()
    assert third["overwrote_newer"] is True
    # no base while a queue exists counts as overwriting
    fourth = (await c.put("/api/me/queue", json=_body([a]))).json()
    assert fourth["overwrote_newer"] is True


@pytest.mark.asyncio
async def test_queue_drops_invisible_sets_and_keeps_current(
    authed_admin_client, seeded_live_set,
):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    b, d = await _more_sets(seeded_live_set, 2)
    await c.put("/api/me/queue", json=_body([a, b, d], 2))
    await _set_state(a, deleted_at=datetime.now(UTC))
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [b, d]
    assert got["slugs"][got["index"]] == d
    # the current set goes away: the index moves on to what is left
    await _set_state(d, status="draft")
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [b]
    assert got["index"] == 0
    # restored: they come back
    await _set_state(a, deleted_at=None)
    await _set_state(d, status="published")
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [a, b, d]
    assert got["index"] == 2


@pytest.mark.asyncio
async def test_put_unknown_slugs_dropped_and_index_reaimed(
    authed_admin_client, seeded_live_set,
):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    (b,) = await _more_sets(seeded_live_set, 1)
    ghost = "ghost-" + uuid.uuid4().hex
    r = await c.put("/api/me/queue", json=_body([ghost, a, ghost, b], 3))
    assert r.status_code == 200, r.text
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [a, b]
    assert got["index"] == 1  # still on b
    # index past the end: clamped
    await c.put("/api/me/queue", json=_body([a, b], 99))
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [a, b] and got["index"] == 1
    # index on an unknown slug: clamped into the kept list
    await c.put("/api/me/queue", json=_body([a, ghost, b], 1))
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [a, b] and got["index"] == 1
    # draft and soft-deleted slugs are dropped like unknown ones
    draft, gone = await _more_sets(seeded_live_set, 2)
    await _set_state(draft, status="draft")
    await _set_state(gone, deleted_at=datetime.now(UTC))
    await c.put("/api/me/queue", json=_body([a, draft, gone, b], 3))
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [a, b] and got["index"] == 1
    await c.put("/api/me/queue", json=_body([a, b, draft], 2))
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [a, b] and got["index"] == 1
    # nothing resolves: an empty queue
    await c.put("/api/me/queue", json=_body([ghost]))
    got = (await c.get("/api/me/queue")).json()
    assert got["slugs"] == [] and got["index"] == 0
    assert (await c.put("/api/me/queue", json=_body([], -1))).status_code == 422


@pytest.mark.asyncio
async def test_queue_is_per_user(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    await c.put("/api/me/queue", json=_body([a]))
    async with session_factory()() as s:
        s.add(User(email="q-member@x.test", username="q-member", display_name="Q",
                   password_hash=hash_password("hunter2hunter2"), role="member"))
        await s.commit()
    login = await c.post("/api/auth/login",
                         json={"email": "q-member@x.test", "password": "hunter2hunter2"})
    c.cookies = login.cookies
    c.headers["X-CSRF-Token"] = login.cookies["csrf_token"]
    assert (await c.get("/api/me/queue")).json() == {
        "slugs": [], "index": 0, "updated_at": None}


@pytest.mark.asyncio
async def test_too_many_slugs_is_400(authed_admin_client):
    c = authed_admin_client
    slugs = [f"s-{i}" for i in range(1001)]
    assert (await c.put("/api/me/queue", json=_body(slugs))).status_code == 400
    assert (await c.get("/api/me/queue")).json()["slugs"] == []


@pytest.mark.asyncio
async def test_requires_login(client):
    assert (await client.get("/api/me/queue")).status_code == 401
    assert (await client.put("/api/me/queue", json=_body([]))).status_code in (401, 403)


@pytest.mark.asyncio
async def test_queue_exactly_1000_slugs_ok(authed_admin_client, seeded_live_set, monkeypatch):
    from setvault_core.services import play_queue as svc

    monkeypatch.setattr(svc, "MAX_QUEUE", 3)
    c = authed_admin_client
    a = seeded_live_set["slug"]
    b, d, e = await _more_sets(seeded_live_set, 3)
    ok = await c.put("/api/me/queue", json=_body([a, b, d], 2))
    assert ok.status_code == 200, ok.text
    assert (await c.get("/api/me/queue")).json()["slugs"] == [a, b, d]
    assert (await c.put("/api/me/queue", json=_body([a, b, d, e]))).status_code == 400

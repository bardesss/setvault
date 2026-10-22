import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.engagement import Favorite
from sqlalchemy import func, select


async def _count_favorites() -> int:
    async with session_factory()() as s:
        return (await s.execute(select(func.count()).select_from(Favorite))).scalar_one()


@pytest.mark.asyncio
async def test_favorite_put_is_idempotent(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    r1 = await authed_admin_client.put(f"/api/sets/{slug}/favorite")
    r2 = await authed_admin_client.put(f"/api/sets/{slug}/favorite")
    assert r1.status_code == 204
    assert r2.status_code == 204
    assert await _count_favorites() == 1


@pytest.mark.asyncio
async def test_unfavorite_never_favorited_is_204(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.delete(f"/api/sets/{slug}/favorite")
    assert r.status_code == 204
    await authed_admin_client.put(f"/api/sets/{slug}/favorite")
    assert (await authed_admin_client.delete(f"/api/sets/{slug}/favorite")).status_code == 204
    assert await _count_favorites() == 0


@pytest.mark.asyncio
async def test_favorite_deleted_set_404(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    async with session_factory()() as s:
        live = (await s.execute(select(LiveSet).where(LiveSet.slug == slug))).scalar_one()
        live.deleted_at = datetime.now(UTC)
        await s.commit()
    assert (await authed_admin_client.put(f"/api/sets/{slug}/favorite")).status_code == 404
    assert (await authed_admin_client.put("/api/sets/nope-" + uuid.uuid4().hex + "/favorite")
            ).status_code == 404


@pytest.mark.asyncio
async def test_me_favorites_newest_first(authed_admin_client, seeded_live_set):
    async with session_factory()() as s:
        src = (await s.execute(
            select(LiveSet).where(LiveSet.slug == seeded_live_set["slug"])
        )).scalar_one()
        second = LiveSet(
            slug=f"second-{uuid.uuid4().hex[:6]}", title="second",
            media_root_id=src.media_root_id, audio_path="originals/seed/b.flac",
            status="published", source_type="upload", uploaded_by=src.uploaded_by,
        )
        s.add(second)
        await s.commit()
        second_slug = second.slug
    await authed_admin_client.put(f"/api/sets/{seeded_live_set['slug']}/favorite")
    await authed_admin_client.put(f"/api/sets/{second_slug}/favorite")
    r = await authed_admin_client.get("/api/me/favorites?limit=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [i["slug"] for i in body["items"]] == [second_slug]
    item = body["items"][0]
    assert item["favorited_at"] and item["created_at"] and "tags" in item and "venue" in item
    r = await authed_admin_client.get("/api/me/favorites")
    assert [i["slug"] for i in r.json()["items"]] == [second_slug, seeded_live_set["slug"]]
    r = await authed_admin_client.get("/api/me/favorites?limit=1&offset=1")
    assert [i["slug"] for i in r.json()["items"]] == [seeded_live_set["slug"]]


@pytest.mark.asyncio
async def test_show_set_is_favorite_flag(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    assert (await authed_admin_client.get(f"/api/sets/{slug}")).json()["is_favorite"] is False
    await authed_admin_client.put(f"/api/sets/{slug}/favorite")
    assert (await authed_admin_client.get(f"/api/sets/{slug}")).json()["is_favorite"] is True
    await authed_admin_client.delete(f"/api/sets/{slug}/favorite")
    assert (await authed_admin_client.get(f"/api/sets/{slug}")).json()["is_favorite"] is False


@pytest.mark.asyncio
async def test_favorite_requires_auth_and_csrf(client, authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    csrf = authed_admin_client.headers.pop("X-CSRF-Token")
    r = await authed_admin_client.put(f"/api/sets/{slug}/favorite")
    assert r.status_code == 403
    authed_admin_client.headers["X-CSRF-Token"] = csrf
    authed_admin_client.cookies.clear()
    r = await authed_admin_client.put(f"/api/sets/{slug}/favorite")
    assert r.status_code in (401, 403)
    assert (await authed_admin_client.get("/api/me/favorites")).status_code == 401
    assert await _count_favorites() == 0

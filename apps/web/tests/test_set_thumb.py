"""A set's cover: ``thumb_url`` on set summaries and the thumb route."""
from __future__ import annotations

import uuid
from pathlib import Path

from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot


async def _give_thumb(seeded_live_set: dict) -> str:
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))
        rel = f"thumbs/{live.id}.jpg"
        live.thumb_path = rel
        live.embed_allowed = False
        await s.commit()
        root = await s.get(MediaRoot, live.media_root_id)
    target = Path(root.host_path) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xd8\xff\xd9")
    return rel


async def test_summary_has_no_thumb_url_without_a_cover(authed_admin_client, seeded_live_set):
    r = await authed_admin_client.get("/api/sets?limit=50")
    item = next(i for i in r.json()["items"] if i["slug"] == seeded_live_set["slug"])
    assert item["thumb_url"] is None
    r = await authed_admin_client.get(f"/api/sets/{seeded_live_set['slug']}/thumb")
    assert r.status_code == 404


async def test_thumb_is_listed_and_served(authed_admin_client, seeded_live_set):
    await _give_thumb(seeded_live_set)
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.get("/api/sets?limit=50")
    item = next(i for i in r.json()["items"] if i["slug"] == slug)
    assert item["thumb_url"].startswith(f"/api/sets/{slug}/thumb?v=")
    detail = (await authed_admin_client.get(f"/api/sets/{slug}")).json()
    assert detail["thumb_url"] == item["thumb_url"]

    r = await authed_admin_client.get(item["thumb_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8\xff\xd9"


async def test_thumb_needs_a_session(client, authed_admin_client, seeded_live_set):
    await _give_thumb(seeded_live_set)
    client.cookies.clear()
    r = await client.get(f"/api/sets/{seeded_live_set['slug']}/thumb")
    assert r.status_code == 401

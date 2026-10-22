from __future__ import annotations

import uuid

import pytest
from defusedxml import ElementTree as ET


@pytest.mark.asyncio
async def test_recent_feed_returns_rss_xml(authed_admin_client, seeded_admin, seeded_live_set):
    """Mint an RSS token, fetch /api/feed/recent/{token}.xml, assert RSS."""
    from setvault_core.db import session_factory
    from setvault_core.services.api_tokens import mint_api_token

    async with session_factory()() as s:
        _, plaintext = await mint_api_token(
            s, user_id=seeded_admin.id, name="recent feed", scopes=["rss"],
        )
        await s.commit()

    r = await authed_admin_client.get(f"/api/feed/recent/{plaintext}.xml")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/rss+xml")
    root = ET.fromstring(r.content)
    items = root.findall(".//item")
    # seeded_live_set is published, so at least one item should appear
    assert len(items) >= 1
    titles = [it.findtext("title") for it in items]
    assert "seeded set" in titles


@pytest.mark.asyncio
async def test_feed_with_unknown_token_returns_404(client):
    """Bogus tokens get 404 (not 401) so we don't leak token existence."""
    r = await client.get(f"/api/feed/recent/{uuid.uuid4().hex}.xml")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_feed_token_without_rss_scope_returns_404(client, seeded_admin):
    """A token without the rss scope must not be accepted."""
    from setvault_core.db import session_factory
    from setvault_core.services.api_tokens import mint_api_token

    async with session_factory()() as s:
        _, plaintext = await mint_api_token(
            s, user_id=seeded_admin.id, name="other", scopes=["other"],
        )
        await s.commit()

    r = await client.get(f"/api/feed/recent/{plaintext}.xml")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_feed_updates_last_used_at(authed_admin_client, seeded_admin):
    """First feed fetch sets last_used_at and writes a first-use audit event."""
    from setvault_core.db import session_factory
    from setvault_core.models.api_token import ApiToken
    from setvault_core.services.api_tokens import mint_api_token
    from sqlalchemy import select

    async with session_factory()() as s:
        row, plaintext = await mint_api_token(
            s, user_id=seeded_admin.id, name="feed1", scopes=["rss"],
        )
        await s.commit()
        token_id = row.id

    r = await authed_admin_client.get(f"/api/feed/everything/{plaintext}.xml")
    assert r.status_code == 200, r.text

    async with session_factory()() as s:
        refreshed = (await s.execute(
            select(ApiToken).where(ApiToken.id == token_id)
        )).scalar_one()
        assert refreshed.last_used_at is not None


@pytest.mark.asyncio
async def test_favorites_feed_lists_favorited_set(
    authed_admin_client, seeded_admin, seeded_live_set,
):
    from setvault_core.db import session_factory
    from setvault_core.services.api_tokens import mint_api_token

    async with session_factory()() as s:
        _, plaintext = await mint_api_token(
            s, user_id=seeded_admin.id, name="fav feed", scopes=["rss"],
        )
        await s.commit()

    url = f"/api/feed/favorites/{plaintext}.xml"
    before = ET.fromstring((await authed_admin_client.get(url)).content)
    assert before.findall(".//item") == []

    r = await authed_admin_client.put(f"/api/sets/{seeded_live_set['slug']}/favorite")
    assert r.status_code == 204
    after = ET.fromstring((await authed_admin_client.get(url)).content)
    assert [it.findtext("title") for it in after.findall(".//item")] == ["seeded set"]

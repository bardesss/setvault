from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_embed_404_when_not_allowed(client, seeded_live_set):
    """GET /api/sets/{slug}/embed anonymously returns 404 when embed_allowed=false."""
    client.cookies.clear()
    r = await client.get(f"/api/sets/{seeded_live_set['slug']}/embed")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_toggle_then_embed_200(authed_admin_client, seeded_live_set):
    """Admin PATCHes embed_allowed=true; anonymous GET embed then succeeds."""
    r = await authed_admin_client.patch(
        f"/api/sets/{seeded_live_set['slug']}/embed",
        json={"allowed": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["embed_allowed"] is True

    # Drop cookies for anonymous access on a new client
    from httpx import ASGITransport, AsyncClient
    from setvault_web.main import create_app
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="https://test") as anon:
        r = await anon.get(f"/api/sets/{seeded_live_set['slug']}/embed")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["slug"] == seeded_live_set["slug"]
        assert body["title"] == "seeded set"
        assert body["audio_url"] == f"/api/sets/{seeded_live_set['slug']}/stream?v=0.0"
        assert "tracklist" in body


@pytest.mark.asyncio
async def test_non_admin_cannot_toggle_embed(client, seeded_live_set, seeded_admin):
    """Non-admin or anonymous PATCH must be rejected (401 or 403)."""
    client.cookies.clear()
    r = await client.patch(
        f"/api/sets/{seeded_live_set['slug']}/embed",
        json={"allowed": True},
    )
    assert r.status_code in (401, 403)

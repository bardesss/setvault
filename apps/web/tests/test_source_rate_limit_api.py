import pytest


@pytest.mark.asyncio
async def test_list_includes_rate_limit_fields(authed_admin_client):
    r = await authed_admin_client.get("/api/admin/ingest-sources")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert "rate_limit_max" in item
    assert "rate_limit_window_seconds" in item


@pytest.mark.asyncio
async def test_put_updates_rate_limit(authed_admin_client):
    r = await authed_admin_client.put("/api/admin/ingest-sources/youtube",
                                      json={"enabled": True, "rate_limit_max": 7,
                                            "rate_limit_window_seconds": 120})
    assert r.status_code == 200
    body = r.json()
    assert body["rate_limit_max"] == 7
    assert body["rate_limit_window_seconds"] == 120


@pytest.mark.asyncio
async def test_window_zero_rejected(authed_admin_client):
    r = await authed_admin_client.put("/api/admin/ingest-sources/youtube",
                                      json={"enabled": True, "rate_limit_window_seconds": 0})
    assert r.status_code == 422
    r = await authed_admin_client.put("/api/admin/ingest-sources/youtube",
                                      json={"enabled": True, "rate_limit_window_seconds": 1})
    assert r.status_code == 200

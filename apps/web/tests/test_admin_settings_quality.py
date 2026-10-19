from __future__ import annotations

import pytest

ORDER = ["lossless", "high", "good", "ok", "low"]


@pytest.mark.asyncio
async def test_put_settings_validates_quality_fields(authed_admin_client):
    c = authed_admin_client
    body = (await c.get("/api/admin/settings")).json()
    assert body["quality_tiers_order"] == ORDER
    assert body["quality_cutoff"] == "lossless"
    assert body["auto_upgrades_enabled"] is True
    assert body["upgrade_search_schedule"] == "weekly"

    for bad in (
        {"quality_tiers_order": ["lossless", "high", "good", "ok"]},
        {"quality_tiers_order": ["lossless", "high", "good", "ok", "ok"]},
        {"quality_tiers_order": ["lossless", "high", "good", "ok", "bogus"]},
        {"quality_cutoff": "platinum"},
        {"upgrade_search_schedule": "hourly"},
    ):
        r = await c.put("/api/admin/settings", json=bad)
        assert r.status_code == 422, (bad, r.text)

    try:
        new_order = ["high", "lossless", "good", "ok", "low"]
        r = await c.put("/api/admin/settings", json={
            "quality_tiers_order": new_order,
            "quality_cutoff": "high",
            "auto_upgrades_enabled": False,
            "upgrade_search_schedule": "daily",
        })
        assert r.status_code == 200, r.text
        got = (await c.get("/api/admin/settings")).json()
        assert got["quality_tiers_order"] == new_order
        assert got["quality_cutoff"] == "high"
        assert got["auto_upgrades_enabled"] is False
        assert got["upgrade_search_schedule"] == "daily"
    finally:
        await c.put("/api/admin/settings", json={
            "quality_tiers_order": ORDER,
            "quality_cutoff": "lossless",
            "auto_upgrades_enabled": True,
            "upgrade_search_schedule": "weekly",
        })


@pytest.mark.asyncio
async def test_partial_put_leaves_untouched_fields_unchanged(authed_admin_client):
    c = authed_admin_client
    before = (await c.get("/api/admin/settings")).json()
    try:
        r = await c.put("/api/admin/settings", json={"quality_cutoff": "high"})
        assert r.status_code == 200, r.text
        after = (await c.get("/api/admin/settings")).json()
        assert after["quality_cutoff"] == "high"
        assert {k: v for k, v in after.items() if k != "quality_cutoff"} == {
            k: v for k, v in before.items() if k != "quality_cutoff"
        }
    finally:
        await c.put("/api/admin/settings", json={"quality_cutoff": before["quality_cutoff"]})


@pytest.mark.asyncio
async def test_get_settings_tolerates_unknown_stored_schedule(authed_admin_client):
    from setvault_core.db import session_factory
    from setvault_core.services.system_config import get_config

    async with session_factory()() as s:
        cfg = await get_config(s)
        cfg.upgrade_search_schedule = "hourly"
        await s.commit()
    try:
        r = await authed_admin_client.get("/api/admin/settings")
        assert r.status_code == 200, r.text
        assert r.json()["upgrade_search_schedule"] == "weekly"
    finally:
        async with session_factory()() as s:
            cfg = await get_config(s)
            cfg.upgrade_search_schedule = "weekly"
            await s.commit()

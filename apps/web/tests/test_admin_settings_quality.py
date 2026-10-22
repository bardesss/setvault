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


@pytest.mark.asyncio
async def test_unknown_schedule_is_weekly_everywhere(authed_admin_client, seeded_live_set):
    """A stored schedule outside daily/weekly/off reads as weekly in the
    settings AND the scheduler searches on the weekly window (not "off")."""
    import uuid
    from datetime import UTC, datetime, timedelta

    from setvault_core.db import session_factory
    from setvault_core.jobs.upgrade_search import due_sets, normalize_schedule
    from setvault_core.models.catalog import LiveSet, SetFingerprint
    from setvault_core.services.audio_match import MATCHER_VERSION
    from setvault_core.services.system_config import get_config

    assert normalize_schedule("daily") == "daily"
    assert normalize_schedule("off") == "off"
    assert normalize_schedule("hourly") == "weekly"
    assert normalize_schedule(None) == "weekly"

    sid = uuid.UUID(seeded_live_set["id"])
    now = datetime.now(UTC)
    async with session_factory()() as s:
        cfg = await get_config(s)
        before = (cfg.upgrade_search_schedule, cfg.auto_upgrades_enabled)
        cfg.upgrade_search_schedule = "hourly"
        cfg.auto_upgrades_enabled = True
        live = await s.get(LiveSet, sid)
        live.quality_tier = "low"
        live.last_upgrade_search_at = now - timedelta(hours=48)
        s.add(SetFingerprint(
            live_set_id=sid, fingerprint_hash=uuid.uuid4().hex, duration_seconds=120.0,
            raw=bytes(4), raw_version=MATCHER_VERSION,
        ))
        await s.commit()
    try:
        r = await authed_admin_client.get("/api/admin/settings")
        assert r.json()["upgrade_search_schedule"] == "weekly"

        async def due() -> bool:
            async with session_factory()() as s:
                rows = await due_sets(s, now=now, schedule="hourly", limit=10_000)
                return sid in {x.id for x in rows}

        assert not await due()  # 48 h ago: inside the weekly window
        async with session_factory()() as s:
            (await s.get(LiveSet, sid)).last_upgrade_search_at = now - timedelta(days=10)
            await s.commit()
        assert await due()
    finally:
        async with session_factory()() as s:
            cfg = await get_config(s)
            cfg.upgrade_search_schedule, cfg.auto_upgrades_enabled = before
            await s.commit()

"""Set detail: quality, the per-set upgrade switch and upgrade history."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.upgrades import SetUpgradeEvent


@pytest.mark.asyncio
async def test_set_detail_includes_quality_and_history(authed_admin_client, seeded_live_set):
    sid, slug = seeded_live_set["id"], seeded_live_set["slug"]
    body = (await authed_admin_client.get(f"/api/sets/{slug}")).json()
    assert body["quality"] is None
    assert body["upgrades_enabled"] is True
    assert body["upgrade_history"] == []

    now = datetime.now(UTC)
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(sid))
        live.quality_tier = "lossless"
        live.audio_codec = "flac"
        live.source_type = "bandcamp"
        for i in range(7):
            s.add(SetUpgradeEvent(
                live_set_id=live.id, trigger="scheduled", outcome="upgraded",
                created_at=now - timedelta(days=10 - i),
                from_tier="ok", from_codec="mp3", from_bitrate_kbps=128 + i,
                to_tier="lossless", to_codec="flac",
                to_source_type="bandcamp",
            ))
        s.add(SetUpgradeEvent(
            live_set_id=live.id, trigger="scheduled", outcome="rejected",
            created_at=now,
        ))
        await s.commit()

    body = (await authed_admin_client.get(f"/api/sets/{slug}")).json()
    assert body["quality"]["tier"] == "lossless"
    assert body["quality"]["label"].startswith("FLAC")
    hist = body["upgrade_history"]
    assert len(hist) == 5  # capped; the rejected event is excluded
    assert hist[0]["from_label"].startswith("MP3 134 kbps")  # newest first
    assert hist[0]["to_label"].startswith("FLAC")
    # Unique keys for the page's list, even for events written in one
    # transaction (same now()).
    assert len({h["id"] for h in hist}) == 5


@pytest.mark.asyncio
async def test_patch_upgrades_enabled_requires_edit_permission(
    authed_admin_client, seeded_live_set, client,
):
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.patch(f"/api/sets/{slug}", json={"upgrades_enabled": False})
    assert r.status_code == 200
    assert r.json()["upgrades_enabled"] is False
    r = await authed_admin_client.patch(f"/api/sets/{slug}", json={"title": "Other"})
    assert r.json()["upgrades_enabled"] is False  # untouched by other edits

    client.cookies.clear()
    r = await client.patch(f"/api/sets/{slug}", json={"upgrades_enabled": True})
    assert r.status_code in (401, 403)
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))
        assert live.upgrades_enabled is False

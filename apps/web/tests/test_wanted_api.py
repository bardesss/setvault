"""Admin Wanted list: cutoff-unmet sets and the Search now button."""
from __future__ import annotations

import uuid

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.upgrades import SetUpgradeEvent


async def _set_quality(set_id: str, **fields) -> None:
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(set_id))
        for k, v in fields.items():
            setattr(live, k, v)
        await s.commit()


@pytest.mark.asyncio
async def test_wanted_lists_only_cutoff_unmet_with_upgrades_on(
    authed_admin_client, seeded_live_set,
):
    sid = seeded_live_set["id"]
    await _set_quality(
        sid, quality_tier="ok", audio_codec="mp3", audio_bitrate_kbps=128,
    )
    async with session_factory()() as s:
        s.add(SetUpgradeEvent(
            live_set_id=uuid.UUID(sid), trigger="scheduled", outcome="rejected",
            reason="not better",
        ))
        await s.commit()

    items = (await authed_admin_client.get("/api/admin/wanted")).json()["items"]
    (item,) = [i for i in items if i["id"] == sid]
    assert item["quality_tier"] == "ok"
    assert item["quality_label"].startswith("MP3 128 kbps")
    assert item["last_event"]["outcome"] == "rejected"
    assert item["last_upgrade_search_at"] is None

    await _set_quality(sid, quality_tier="lossless")  # meets the cutoff
    items = (await authed_admin_client.get("/api/admin/wanted")).json()["items"]
    assert sid not in {i["id"] for i in items}

    await _set_quality(sid, quality_tier="ok", upgrades_enabled=False)
    items = (await authed_admin_client.get("/api/admin/wanted")).json()["items"]
    assert sid not in {i["id"] for i in items}

    await _set_quality(sid, quality_tier=None, upgrades_enabled=True)  # unmeasured
    items = (await authed_admin_client.get("/api/admin/wanted")).json()["items"]
    assert sid not in {i["id"] for i in items}


@pytest.mark.asyncio
async def test_search_now_dedups_in_flight(authed_admin_client, seeded_live_set, monkeypatch):
    await _set_quality(seeded_live_set["id"], quality_tier="low")
    calls: list[uuid.UUID] = []
    results = iter([True, False])

    def fake_enqueue(set_id):
        calls.append(set_id)
        return next(results)

    monkeypatch.setattr(
        "setvault_web.api.wanted.enqueue_search_upgrade_now", fake_enqueue,
    )
    url = f"/api/admin/wanted/{seeded_live_set['slug']}/search"

    r1 = await authed_admin_client.post(url)
    r2 = await authed_admin_client.post(url)

    assert r1.status_code == r2.status_code == 202
    assert r1.json() == {"status": "queued"}
    assert r2.json() == {"status": "already_queued"}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_search_now_rejects_set_meeting_cutoff(authed_admin_client, seeded_live_set):
    await _set_quality(seeded_live_set["id"], quality_tier="lossless")
    r = await authed_admin_client.post(f"/api/admin/wanted/{seeded_live_set['slug']}/search")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_wanted_admin_only(client):
    assert (await client.get("/api/admin/wanted")).status_code in (401, 403)
    assert (await client.post("/api/admin/wanted/x/search")).status_code in (401, 403)

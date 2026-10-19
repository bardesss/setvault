"""Admin Wanted list: cutoff-unmet sets and the Search now button."""
from __future__ import annotations

import uuid

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet, SetFingerprint
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.services.audio_match import MATCHER_VERSION


async def _set_quality(set_id: str, **fields) -> None:
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(set_id))
        for k, v in fields.items():
            setattr(live, k, v)
        await s.commit()


async def _fingerprint(set_id: str, *, raw_version: int | None = MATCHER_VERSION) -> None:
    async with session_factory()() as s:
        s.add(SetFingerprint(
            live_set_id=uuid.UUID(set_id), fingerprint_hash=uuid.uuid4().hex,
            duration_seconds=120.0, raw=bytes(4), raw_version=raw_version,
        ))
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
    await _fingerprint(seeded_live_set["id"])
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


@pytest.mark.asyncio
async def test_wanted_lists_never_searched_first(authed_admin_client, seeded_live_set):
    from datetime import UTC, datetime

    first = seeded_live_set["id"]
    await _set_quality(first, quality_tier="low", last_upgrade_search_at=datetime.now(UTC))
    async with session_factory()() as s:
        src = await s.get(LiveSet, uuid.UUID(first))
        other = LiveSet(
            slug=f"never-{uuid.uuid4().hex[:6]}", title="never searched",
            media_root_id=src.media_root_id, audio_path="originals/n/a.mp3",
            status="published", source_type="upload", quality_tier="low",
            uploaded_by=src.uploaded_by,
        )
        s.add(other)
        await s.commit()
        other_id = str(other.id)

    items = (await authed_admin_client.get("/api/admin/wanted")).json()["items"]
    ids = [i["id"] for i in items]
    assert ids.index(other_id) < ids.index(first)


@pytest.mark.asyncio
async def test_wanted_label_names_the_rip_platform(authed_admin_client, seeded_live_set):
    """R26: one label format with the set page: a url_rip shows its platform."""
    sid = seeded_live_set["id"]
    await _set_quality(
        sid, quality_tier="ok", audio_codec="mp3", audio_bitrate_kbps=128,
        source_type="url_rip", source_url="https://www.youtube.com/watch?v=abcdefghijk",
    )
    items = (await authed_admin_client.get("/api/admin/wanted")).json()["items"]
    (item,) = [i for i in items if i["id"] == sid]
    assert item["quality_label"] == "MP3 128 kbps (YouTube)"


@pytest.mark.asyncio
async def test_wanted_newest_event_is_deterministic_on_ties(
    authed_admin_client, seeded_live_set,
):
    from datetime import UTC, datetime

    sid = uuid.UUID(seeded_live_set["id"])
    await _set_quality(str(sid), quality_tier="ok")
    at = datetime.now(UTC)
    ids = sorted([uuid.uuid4(), uuid.uuid4()])
    async with session_factory()() as s:
        # Inserted largest id first, same timestamp (one transaction's now()).
        for eid, reason in ((ids[1], "second"), (ids[0], "first")):
            s.add(SetUpgradeEvent(id=eid, live_set_id=sid, trigger="scheduled",
                                  outcome="rejected", reason=reason, created_at=at))
        await s.commit()
    for _ in range(3):
        items = (await authed_admin_client.get("/api/admin/wanted")).json()["items"]
        (item,) = [i for i in items if i["id"] == str(sid)]
        assert item["last_event"]["reason"] == "second"


@pytest.mark.asyncio
async def test_search_now_refuses_sets_with_upgrades_off_or_unmeasured(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    monkeypatch.setattr(
        "setvault_web.api.wanted.enqueue_search_upgrade_now", lambda set_id: True,
    )
    url = f"/api/admin/wanted/{seeded_live_set['slug']}/search"
    await _set_quality(seeded_live_set["id"], quality_tier="low", upgrades_enabled=False)
    r = await authed_admin_client.post(url)
    assert r.status_code == 409
    assert r.json()["detail"] == "upgrades are off for this set"

    await _set_quality(seeded_live_set["id"], quality_tier=None, upgrades_enabled=True)
    r = await authed_admin_client.post(url)
    assert r.status_code == 409
    assert r.json()["detail"] == "quality not measured yet"


@pytest.mark.asyncio
async def test_search_now_refuses_sets_not_fingerprinted_yet(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(
        "setvault_web.api.wanted.enqueue_search_upgrade_now",
        lambda set_id: calls.append(set_id) or True,
    )
    url = f"/api/admin/wanted/{seeded_live_set['slug']}/search"
    await _set_quality(seeded_live_set["id"], quality_tier="low")

    r = await authed_admin_client.post(url)
    assert (r.status_code, r.json()["detail"]) == (409, "not fingerprinted yet")

    # a stale-version fingerprint doesn't count either
    await _fingerprint(seeded_live_set["id"], raw_version=MATCHER_VERSION - 1)
    assert (await authed_admin_client.post(url)).status_code == 409
    assert calls == []

    await _fingerprint(seeded_live_set["id"])
    assert (await authed_admin_client.post(url)).status_code == 202
    assert len(calls) == 1

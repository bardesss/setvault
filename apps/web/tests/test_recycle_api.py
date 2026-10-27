"""Restore from the recycle bin re-queues a missing stream."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_web.api import recycle


async def _recycle(set_id: str, *, streaming_path: str | None) -> None:
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(set_id))
        live.streaming_path = streaming_path
        live.deleted_at = datetime.now(UTC)
        await s.commit()


def _capture_enqueue(monkeypatch) -> list[uuid.UUID]:
    queued: list[uuid.UUID] = []

    def _enqueue(set_id: uuid.UUID) -> bool:
        queued.append(set_id)
        return True

    monkeypatch.setattr(recycle, "enqueue_transcode", _enqueue)
    return queued


def _write_audio(tmp_path: Path) -> None:
    audio = tmp_path / "originals/seed/audio.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"flac")


@pytest.mark.asyncio
async def test_restore_queues_transcode_for_set_without_stream(
    authed_admin_client, seeded_live_set, tmp_path, monkeypatch,
):
    _write_audio(tmp_path)
    await _recycle(seeded_live_set["id"], streaming_path=None)
    queued = _capture_enqueue(monkeypatch)

    r = await authed_admin_client.post(f"/api/admin/recycle/{seeded_live_set['slug']}/restore")

    assert r.status_code == 200, r.text
    assert queued == [uuid.UUID(seeded_live_set["id"])]
    async with session_factory()() as s:
        assert (await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))).deleted_at is None


@pytest.mark.asyncio
async def test_restore_with_stream_queues_nothing(
    authed_admin_client, seeded_live_set, tmp_path, monkeypatch,
):
    _write_audio(tmp_path)
    await _recycle(seeded_live_set["id"], streaming_path="stream/x.opus")
    queued = _capture_enqueue(monkeypatch)

    r = await authed_admin_client.post(f"/api/admin/recycle/{seeded_live_set['slug']}/restore")

    assert r.status_code == 200, r.text
    assert queued == []


@pytest.mark.asyncio
async def test_restore_without_audio_file_queues_nothing(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    await _recycle(seeded_live_set["id"], streaming_path=None)
    queued = _capture_enqueue(monkeypatch)

    r = await authed_admin_client.post(f"/api/admin/recycle/{seeded_live_set['slug']}/restore")

    assert r.status_code == 200, r.text
    assert queued == []


@pytest.mark.asyncio
async def test_restore_survives_enqueue_failure(
    authed_admin_client, seeded_live_set, tmp_path, monkeypatch,
):
    """The real enqueue_transcode with Redis failing: logged, restore holds."""
    import rq

    class _Broken:
        def __init__(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(rq, "Queue", _Broken)
    _write_audio(tmp_path)
    await _recycle(seeded_live_set["id"], streaming_path=None)

    r = await authed_admin_client.post(f"/api/admin/recycle/{seeded_live_set['slug']}/restore")

    assert r.status_code == 200, r.text
    async with session_factory()() as s:
        assert (await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))).deleted_at is None


@pytest.fixture
def fired(monkeypatch):
    """Every ``fan_out_webhook_event`` call as ``(event, slug)``."""
    from setvault_core.jobs import ready

    calls: list[tuple[str, str | None]] = []

    async def fake(event, *, set_slug, set_id, title):
        calls.append((event, set_slug))

    monkeypatch.setattr(ready, "fan_out_webhook_event", fake)
    return calls


@pytest.mark.asyncio
async def test_restore_fires_restored(authed_admin_client, seeded_live_set, fired):
    await _recycle(seeded_live_set["id"], streaming_path="stream/x.opus")
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.post(f"/api/admin/recycle/{slug}/restore")
    assert r.status_code == 200, r.text
    assert fired == [("set.restored", slug)]


@pytest.mark.asyncio
async def test_purge_now_fires_purged(authed_admin_client, seeded_live_set, fired):
    await _recycle(seeded_live_set["id"], streaming_path="stream/x.opus")
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.post(f"/api/admin/recycle/{slug}/purge-now")
    assert r.status_code == 204, r.text
    assert fired == [("set.purged", slug)]
    async with session_factory()() as s:
        assert await s.get(LiveSet, uuid.UUID(seeded_live_set["id"])) is None


@pytest.mark.asyncio
async def test_purge_now_of_a_draft_fires_nothing(authed_admin_client, seeded_live_set, fired):
    await _recycle(seeded_live_set["id"], streaming_path=None)
    async with session_factory()() as s:
        (await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))).status = "draft"
        await s.commit()
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.post(f"/api/admin/recycle/{slug}/purge-now")
    assert r.status_code == 204, r.text
    assert fired == []

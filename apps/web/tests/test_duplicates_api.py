"""Admin review queue for fingerprint duplicates held as drafts."""
from __future__ import annotations

import uuid

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.engagement import ActivityEvent
from sqlalchemy import select


async def _held_duplicate(original_id: str) -> tuple[str, uuid.UUID]:
    async with session_factory()() as s:
        original = await s.get(LiveSet, uuid.UUID(original_id))
        dup = LiveSet(
            slug=f"dup-{uuid.uuid4().hex[:6]}", title="dup copy",
            media_root_id=original.media_root_id, audio_path="originals/dup/a.flac",
            status="draft", source_type="upload", uploaded_by=original.uploaded_by,
            duplicate_of=original.id,
        )
        s.add(dup)
        await s.commit()
        return dup.slug, dup.id


@pytest.mark.asyncio
async def test_list_shows_held_duplicate_with_original(authed_admin_client, seeded_live_set):
    slug, _ = await _held_duplicate(seeded_live_set["id"])

    r = await authed_admin_client.get("/api/admin/duplicates")

    assert r.status_code == 200, r.text
    (item,) = [i for i in r.json()["items"] if i["slug"] == slug]
    assert item["original"]["slug"] == seeded_live_set["slug"]


@pytest.mark.asyncio
async def test_keep_publishes_and_drops_from_queue(authed_admin_client, seeded_live_set):
    slug, sid = await _held_duplicate(seeded_live_set["id"])

    r = await authed_admin_client.post(f"/api/admin/duplicates/{slug}/keep")

    assert r.status_code == 200, r.text
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).status == "published"
        events = (await s.execute(
            select(ActivityEvent).where(ActivityEvent.subject_id == sid),
        )).scalars().all()
        assert any(e.kind == "set.published" for e in events)
    listed = (await authed_admin_client.get("/api/admin/duplicates")).json()["items"]
    assert slug not in {i["slug"] for i in listed}


@pytest.mark.asyncio
async def test_discard_moves_to_recycle_bin(authed_admin_client, seeded_live_set):
    slug, sid = await _held_duplicate(seeded_live_set["id"])

    r = await authed_admin_client.post(f"/api/admin/duplicates/{slug}/discard")

    assert r.status_code == 204, r.text
    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.deleted_at is not None
        assert row.purge_after_at is not None
    recycled = (await authed_admin_client.get("/api/admin/recycle")).json()["items"]
    assert slug in {i["slug"] for i in recycled}


@pytest.mark.asyncio
async def test_actions_reject_sets_that_are_not_held_duplicates(
    authed_admin_client, seeded_live_set,
):
    slug = seeded_live_set["slug"]  # published, not a duplicate
    for action in ("keep", "discard"):
        r = await authed_admin_client.post(f"/api/admin/duplicates/{slug}/{action}")
        assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_keep_duplicate_stamps_kept_at(authed_admin_client, seeded_live_set):
    slug, sid = await _held_duplicate(seeded_live_set["id"])
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).duplicate_kept_at is None

    r = await authed_admin_client.post(f"/api/admin/duplicates/{slug}/keep")

    assert r.status_code == 200, r.text
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).duplicate_kept_at is not None


@pytest.mark.asyncio
async def test_purge_now_spares_files_another_set_references(
    authed_admin_client, seeded_live_set, tmp_path,
):
    """R15: purge-now deletes the recycled set's own files but never one a
    live set still points at."""
    from datetime import UTC, datetime

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))
        live.streaming_path = "stream/shared.opus"
        gone = LiveSet(
            slug=f"gone-{uuid.uuid4().hex[:6]}", title="old copy",
            media_root_id=live.media_root_id, audio_path="originals/gone/a.mp3",
            streaming_path="stream/shared.opus", status="draft", source_type="upload",
            uploaded_by=live.uploaded_by, deleted_at=datetime.now(UTC),
        )
        s.add(gone)
        await s.commit()
        slug = gone.slug
    for rel in ("originals/gone/a.mp3", "stream/shared.opus"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")

    r = await authed_admin_client.post(f"/api/admin/recycle/{slug}/purge-now")

    assert r.status_code == 204, r.text
    assert not (tmp_path / "originals/gone/a.mp3").exists()
    assert (tmp_path / "stream/shared.opus").exists()

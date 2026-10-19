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


@pytest.mark.asyncio
async def test_restored_replaced_copy_lands_on_the_duplicates_page(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    """R31: after an upgrade the old copy sits in the recycle bin; restoring
    it brings it back as a held duplicate of the upgraded set, not as an
    invisible draft."""
    from setvault_core.services import set_upgrade

    async def _no_webhooks(live, event):
        return None

    monkeypatch.setattr(set_upgrade, "fan_out_webhooks", _no_webhooks)
    tid = uuid.UUID(seeded_live_set["id"])
    async with session_factory()() as s:
        target = await s.get(LiveSet, tid)
        target.quality_tier, target.audio_lossless = "ok", False
        target.streaming_path, target.waveform_path = f"stream/{tid}.opus", f"waveform/{tid}.json"
        arrival = LiveSet(
            slug=f"arr-{uuid.uuid4().hex[:6]}", title="better", media_root_id=target.media_root_id,
            audio_path="originals/arr/a.flac", streaming_path="stream/arr.opus",
            waveform_path="waveform/arr.json", status="draft", source_type="url_rip",
            uploaded_by=target.uploaded_by, duplicate_of=tid, quality_tier="lossless",
            audio_lossless=True,
        )
        s.add(arrival)
        await s.commit()
        aid, aslug = arrival.id, arrival.slug
    async with session_factory()() as s:
        await set_upgrade.apply_upgrade(
            s, target=await s.get(LiveSet, tid), arrival=await s.get(LiveSet, aid),
            trigger="upload",
        )

    r = await authed_admin_client.post(f"/api/admin/recycle/{aslug}/restore")
    assert r.status_code == 200, r.text

    listed = (await authed_admin_client.get("/api/admin/duplicates")).json()["items"]
    (item,) = [i for i in listed if i["slug"] == aslug]
    assert item["original"]["slug"] == seeded_live_set["slug"]


async def _published_match(original_id: str, *, by_backfill: bool) -> tuple[str, uuid.UUID]:
    from datetime import UTC, datetime

    async with session_factory()() as s:
        original = await s.get(LiveSet, uuid.UUID(original_id))
        dup = LiveSet(
            slug=f"pub-{uuid.uuid4().hex[:6]}", title="published copy",
            media_root_id=original.media_root_id, audio_path="originals/pub/a.flac",
            status="published", source_type="upload", uploaded_by=original.uploaded_by,
            duplicate_of=original.id,
            backfill_matched_at=datetime.now(UTC) if by_backfill else None,
        )
        s.add(dup)
        await s.commit()
        return dup.slug, dup.id


@pytest.mark.asyncio
async def test_list_includes_published_sets_matched_by_backfill(
    authed_admin_client, seeded_live_set,
):
    matched, _ = await _published_match(seeded_live_set["id"], by_backfill=True)
    # Published with duplicate_of only = kept before 7D: not listed again.
    kept, _ = await _published_match(seeded_live_set["id"], by_backfill=False)
    held, _ = await _held_duplicate(seeded_live_set["id"])

    items = {i["slug"]: i for i in
             (await authed_admin_client.get("/api/admin/duplicates")).json()["items"]}

    assert items[matched]["reason"] == "matched by backfill"
    assert items[matched]["status"] == "published"
    assert items[matched]["original"]["slug"] == seeded_live_set["slug"]
    assert items[held]["reason"] is None
    assert kept not in items


@pytest.mark.asyncio
async def test_keep_backfill_match_leaves_the_list_without_republishing(
    authed_admin_client, seeded_live_set,
):
    slug, sid = await _published_match(seeded_live_set["id"], by_backfill=True)

    r = await authed_admin_client.post(f"/api/admin/duplicates/{slug}/keep")

    assert r.status_code == 200, r.text
    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.status == "published"
        assert row.duplicate_kept_at is not None and row.backfill_matched_at is None
        events = (await s.execute(
            select(ActivityEvent).where(ActivityEvent.subject_id == sid),
        )).scalars().all()
        assert not any(e.kind == "set.published" for e in events)
    listed = (await authed_admin_client.get("/api/admin/duplicates")).json()["items"]
    assert slug not in {i["slug"] for i in listed}


@pytest.mark.asyncio
async def test_discard_backfill_match_moves_it_to_the_recycle_bin(
    authed_admin_client, seeded_live_set,
):
    slug, sid = await _published_match(seeded_live_set["id"], by_backfill=True)

    r = await authed_admin_client.post(f"/api/admin/duplicates/{slug}/discard")

    assert r.status_code == 204, r.text
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).deleted_at is not None

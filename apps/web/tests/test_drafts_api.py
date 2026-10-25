"""Admin Drafts: list unpublished sets, publish a ready one, discard any
that isn't still being processed."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.url_rip import RipJob


async def _add_set(seed: dict, **fields) -> str:
    async with session_factory()() as s:
        base = await s.get(LiveSet, uuid.UUID(seed["id"]))
        live = LiveSet(**{
            "slug": f"draft-{uuid.uuid4().hex[:8]}", "title": "a draft",
            "media_root_id": base.media_root_id, "audio_path": "originals/d.flac",
            "status": "draft", "source_type": "url_rip", "uploaded_by": base.uploaded_by,
            **fields,
        })
        s.add(live)
        await s.commit()
        return live.slug


async def _add_rip(slug: str, *, status: str, error_text: str | None = None) -> None:
    async with session_factory()() as s:
        live = (await s.execute(
            LiveSet.__table__.select().where(LiveSet.slug == slug)
        )).first()
        s.add(RipJob(
            live_set_id=live.id, submitted_by=live.uploaded_by,
            source_url="https://www.youtube.com/watch?v=x", status=status,
            error_text=error_text,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        ))
        await s.commit()


async def _get(slug: str) -> LiveSet:
    async with session_factory()() as s:
        return (await s.execute(
            LiveSet.__table__.select().where(LiveSet.slug == slug)
        )).first()


@pytest.mark.asyncio
async def test_list_drafts_shows_only_drafts_with_their_state(authed_admin_client, seeded_live_set):
    ready = await _add_set(seeded_live_set, streaming_path="streams/r.m4a")
    broken = await _add_set(seeded_live_set)
    await _add_rip(broken, status="failed", error_text="ffmpeg exited 1")
    busy = await _add_set(seeded_live_set)
    await _add_rip(busy, status="transcoding")
    dup = await _add_set(seeded_live_set, streaming_path="streams/d.m4a",
                         duplicate_of=uuid.UUID(seeded_live_set["id"]))
    await _add_set(seeded_live_set, deleted_at=datetime.now(UTC))

    r = await authed_admin_client.get("/api/admin/drafts")
    assert r.status_code == 200, r.text
    by_slug = {i["slug"]: i for i in r.json()["items"]}
    assert set(by_slug) == {ready, broken, busy, dup}  # not published, not recycled
    assert by_slug[ready]["ready"] is True and by_slug[ready]["processing"] is False
    assert by_slug[broken]["ready"] is False
    assert by_slug[broken]["rip_status"] == "failed"
    assert by_slug[broken]["error"] == "ffmpeg exited 1"
    assert by_slug[busy]["processing"] is True
    assert by_slug[dup]["duplicate_of"]["slug"] == seeded_live_set["slug"]


@pytest.mark.asyncio
async def test_publish_ready_draft(authed_admin_client, seeded_live_set):
    slug = await _add_set(seeded_live_set, streaming_path="streams/r.m4a",
                          duplicate_of=uuid.UUID(seeded_live_set["id"]))
    r = await authed_admin_client.post(f"/api/admin/drafts/{slug}/publish")
    assert r.status_code == 200, r.text
    row = await _get(slug)
    assert row.status == "published"
    assert row.duplicate_kept_at is not None  # a held duplicate is kept, as on Duplicates
    listed = await authed_admin_client.get("/api/sets")
    assert slug in [i["slug"] for i in listed.json()["items"]]


@pytest.mark.asyncio
async def test_publish_refuses_a_draft_without_a_stream(authed_admin_client, seeded_live_set):
    slug = await _add_set(seeded_live_set)
    r = await authed_admin_client.post(f"/api/admin/drafts/{slug}/publish")
    assert r.status_code == 409, r.text
    assert (await _get(slug)).status == "draft"


@pytest.mark.asyncio
async def test_publish_and_discard_only_touch_drafts(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]  # published
    assert (await authed_admin_client.post(f"/api/admin/drafts/{slug}/publish")).status_code == 404
    assert (await authed_admin_client.post(f"/api/admin/drafts/{slug}/discard")).status_code == 404
    assert (await _get(slug)).deleted_at is None


@pytest.mark.asyncio
async def test_discard_moves_draft_to_recycle_bin(authed_admin_client, seeded_live_set):
    slug = await _add_set(seeded_live_set)
    await _add_rip(slug, status="failed")
    r = await authed_admin_client.post(f"/api/admin/drafts/{slug}/discard")
    assert r.status_code == 200, r.text
    row = await _get(slug)
    assert row.deleted_at is not None and row.purge_after_at is not None
    listed = await authed_admin_client.get("/api/admin/drafts")
    assert slug not in [i["slug"] for i in listed.json()["items"]]


@pytest.mark.asyncio
async def test_discard_refuses_a_draft_still_processing(authed_admin_client, seeded_live_set):
    slug = await _add_set(seeded_live_set)
    await _add_rip(slug, status="downloading")
    r = await authed_admin_client.post(f"/api/admin/drafts/{slug}/discard")
    assert r.status_code == 409, r.text
    assert (await _get(slug)).deleted_at is None


@pytest.mark.asyncio
async def test_drafts_require_admin(client):
    assert (await client.get("/api/admin/drafts")).status_code == 401

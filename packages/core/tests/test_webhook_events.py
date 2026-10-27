"""Library webhook events: set.updated, set.deleted, set.restored, set.purged."""
from __future__ import annotations

import array
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import ready
from setvault_core.jobs.bulk_action import bulk_action
from setvault_core.jobs.recycle_bin_purge import purge_recycle_bin
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.services import webhook_events
from setvault_core.services.passwords import hash_password
from setvault_core.services.set_merge import merge_pair


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
def fired(monkeypatch):
    """Every ``fan_out_webhook_event`` call as ``(event, slug, id, title)``."""
    calls: list[tuple] = []

    async def fake(event, *, set_slug, set_id, title):
        calls.append((event, set_slug, set_id, title))

    monkeypatch.setattr(ready, "fan_out_webhook_event", fake)
    return calls


@pytest.fixture
async def lib(tmp_path):
    async with session_factory()() as s:
        root = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path), enabled=True)
        user = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                    display_name="u", password_hash=hash_password("aaaaaaaa"))
        s.add_all([root, user])
        await s.commit()
    return root.id, user.id


async def _add(lib, *, status: str = "published", recycled: bool = False,
               **kw) -> LiveSet:
    root_id, user_id = lib
    sid = uuid.uuid4()
    now = datetime.now(UTC)
    if recycled:
        kw.setdefault("deleted_at", now - timedelta(days=15))
        kw.setdefault("purge_after_at", now - timedelta(days=1))
    async with session_factory()() as s:
        live = LiveSet(
            id=sid, slug=f"s-{sid.hex[:8]}", title=f"Set {sid.hex[:4]}",
            media_root_id=root_id, uploaded_by=user_id, source_type="upload",
            audio_path=f"originals/{sid}/a.flac",
            status=status, **kw,
        )
        s.add(live)
        await s.commit()
    return live


def _event(event: str, live: LiveSet) -> tuple:
    return (event, live.slug, str(live.id), live.title)


async def test_recycling_a_published_set_fires_deleted(fired, lib):
    live = await _add(lib)
    await webhook_events.announce_recycled(live)
    assert fired == [_event("set.deleted", live)]


async def test_recycling_a_draft_fires_nothing(fired, lib):
    draft = await _add(lib, status="draft")
    await webhook_events.announce_recycled(draft)
    await webhook_events.announce_updated(draft)
    await webhook_events.announce_restored(draft)
    # A bulk delete of a draft stays silent too.
    res = await bulk_action(
        action="soft_delete", set_ids=[str(draft.id)], params={}, actor_user_id=None,
    )
    assert res["processed"] == 1
    assert fired == []


async def test_restore_fires_restored(fired, lib):
    live = await _add(lib)
    draft = await _add(lib, status="draft")
    await webhook_events.announce_restored(live)
    await webhook_events.announce_restored(draft)
    assert fired == [_event("set.restored", live)]


async def test_edit_helper_fires_updated_for_published_only(fired, lib):
    live = await _add(lib)
    draft = await _add(lib, status="draft")
    await webhook_events.announce_updated(live)
    await webhook_events.announce_updated(draft)
    assert fired == [_event("set.updated", live)]


async def test_purge_job_fires_purged_for_published_only(fired, lib):
    published = await _add(lib, recycled=True)
    draft = await _add(lib, status="draft", recycled=True)
    assert await purge_recycle_bin() == {"purged": 2, "errors": 0}
    assert fired == [_event("set.purged", published)]
    async with session_factory()() as s:
        assert await s.get(LiveSet, published.id) is None
        assert await s.get(LiveSet, draft.id) is None


async def test_merge_loser_fires_deleted(fired, lib):
    survivor = await _add(lib)
    loser = await _add(lib)
    async with session_factory()() as s:
        await merge_pair(
            s, survivor=await s.get(LiveSet, survivor.id), loser=await s.get(LiveSet, loser.id),
        )
    # The merge flips the loser to draft and retitles it; the event still
    # goes out, with the title users knew.
    assert fired == [_event("set.deleted", loser)]
    async with session_factory()() as s:
        assert (await s.get(LiveSet, loser.id)).title.endswith("(merged copy)")


async def test_merge_of_a_draft_loser_fires_nothing(fired, lib):
    survivor = await _add(lib)
    loser = await _add(lib, status="draft")
    async with session_factory()() as s:
        await merge_pair(
            s, survivor=await s.get(LiveSet, survivor.id), loser=await s.get(LiveSet, loser.id),
        )
    assert fired == []


async def test_bulk_delete_fires_deleted_per_set(fired, lib):
    a, b = await _add(lib), await _add(lib)
    draft = await _add(lib, status="draft")
    already = await _add(lib, recycled=True)
    res = await bulk_action(
        action="soft_delete", params={}, actor_user_id=None,
        set_ids=[str(x.id) for x in (a, b, draft, already)],
    )
    assert res["processed"] == 4
    assert fired == [_event("set.deleted", a), _event("set.deleted", b)]


async def test_announce_never_raises(monkeypatch, lib):
    live = await _add(lib)

    async def boom(*a, **k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(ready, "fan_out_webhook_event", boom)
    await webhook_events.announce_recycled(live)
    await webhook_events.announce_purged(
        was_published=True, set_slug="x", set_id="1", title="t",
    )


async def test_fingerprint_restore_and_recycle(fired, lib, monkeypatch, tmp_path):
    """A new arrival that duplicates a recycled, published set: the old set
    is restored (set.restored); the draft arrival goes to the bin silently."""
    from types import SimpleNamespace

    from setvault_core.jobs import fingerprint as fp

    existing = await _add(lib, recycled=True, quality_tier="ok", audio_lossless=False)
    arrival = await _add(lib, status="draft", quality_tier="ok", audio_lossless=False)
    raw = array.array("I", [1, 2, 3])
    monkeypatch.setattr(fp, "compute_raw_fingerprint", lambda path: (raw, 60.0))
    monkeypatch.setattr(fp, "compute_legacy_digest", lambda path: "digest")

    async def match(*a, **k):
        async with session_factory()() as s:
            return await s.get(LiveSet, existing.id), SimpleNamespace(
                similarity=1.0, offset_seconds=0.0,
            )

    monkeypatch.setattr(fp, "find_original_match", match)

    await fp.fingerprint_audio(str(arrival.id))

    assert fired == [_event("set.restored", existing)]
    async with session_factory()() as s:
        assert (await s.get(LiveSet, existing.id)).deleted_at is None
        assert (await s.get(LiveSet, arrival.id)).deleted_at is not None

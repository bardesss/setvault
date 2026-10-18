"""Watcher catch-up scan + heartbeat against a real DB."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.watch_folder import UnmatchedFile, WatchFolder
from setvault_core.services.watcher import _catch_up, _heartbeat
from sqlalchemy import delete


@pytest.fixture(autouse=True)
async def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])
    yield
    # watch_folders RESTRICTs media_roots deletes in the shared cleanup, so
    # drop this module's rows (and their sets) first.
    async with session_factory()() as s:
        await s.execute(delete(LiveSet).where(LiveSet.source_type == "watch_folder"))
        await s.execute(delete(WatchFolder).where(WatchFolder.id.in_(_created)))
        await s.commit()
    _created.clear()


_created: list[uuid.UUID] = []


async def _folder(tmp_path, *, last_watched_at):
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path / "media"),
                      enabled=True, default_for_ingest=False)
        s.add_all([u, r])
        await s.flush()
        wf = WatchFolder(name="w", host_path=str(tmp_path / f"watch-{uuid.uuid4().hex[:6]}"),
                         target_media_root_id=r.id, enabled=True,
                         last_watched_at=last_watched_at)
        s.add(wf)
        await s.commit()
        _created.append(wf.id)
        return wf, u, r


async def test_catch_up_skips_paths_already_ingested_or_unmatched(tmp_path):
    wf, u, r = await _folder(tmp_path, last_watched_at=None)
    root = tmp_path / wf.host_path
    root.mkdir(parents=True)
    ingested, unmatched, fresh = (root / n for n in ("a.flac", "b.flac", "c.flac"))
    for p in (ingested, unmatched, fresh):
        p.write_bytes(b"x")
    async with session_factory()() as s:
        s.add(LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="a", media_root_id=r.id,
                      audio_path="originals/x/a.flac", uploaded_by=u.id, status="published",
                      source_type="watch_folder", source_url=str(ingested)))
        s.add(UnmatchedFile(watch_folder_id=wf.id, file_path=str(unmatched), audio_info={}))
        await s.commit()

    added: list[tuple[uuid.UUID, str]] = []
    async with session_factory()() as s:
        row = await s.get(WatchFolder, wf.id)
        assert await _catch_up(s, row, lambda wf_id, p: added.append((wf_id, p))) == 1

    assert added == [(wf.id, str(fresh))]


async def test_heartbeat_stamps_observed_folders(tmp_path):
    before = datetime.now(UTC) - timedelta(days=1)
    wf, _, _ = await _folder(tmp_path, last_watched_at=before)

    async with session_factory()() as s:
        await _heartbeat(s, [wf.id])

    async with session_factory()() as s:
        row = await s.get(WatchFolder, wf.id)
        assert row.last_watched_at > before + timedelta(hours=23)

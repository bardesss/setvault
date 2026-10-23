"""apply_naming_to_set (P2a A4): one set's audio file is moved to the path
its media root's naming template renders, without ever losing or
overwriting a file."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.apply_naming import apply_naming_one, apply_naming_to_set
from setvault_core.models.catalog import Artist, LiveSet, LiveSetArtist, MediaRoot
from setvault_core.models.identity import User
from sqlalchemy import delete

TEMPLATE = "{Artist}/{Slug}.{Ext}"


@pytest.fixture(autouse=True)
async def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])
    yield
    async with session_factory()() as s:
        await s.execute(delete(LiveSet))
        await s.execute(delete(Artist).where(Artist.slug.like("naming-test-%")))
        await s.commit()


async def _root(tmp_path: Path, template: str | None = TEMPLATE) -> dict:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, naming_template=template)
        a = Artist(name="Carl Cox", slug=f"naming-test-{uuid.uuid4().hex[:8]}")
        s.add_all([u, r, a])
        await s.commit()
        return {"user": u.id, "root": r.id, "artist": a.id}


async def _set(tmp_path: Path, ids: dict, *, slug: str, audio_path: str,
               data: bytes | None = b"AUDIO") -> uuid.UUID:
    async with session_factory()() as s:
        live = LiveSet(slug=slug, title=slug, media_root_id=ids["root"],
                       audio_path=audio_path, uploaded_by=ids["user"],
                       source_type="upload", status="published")
        s.add(live)
        await s.flush()
        s.add(LiveSetArtist(live_set_id=live.id, artist_id=ids["artist"], position=0))
        await s.commit()
        sid = live.id
    if data is not None:
        p = tmp_path / audio_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return sid


async def _apply(sid: uuid.UUID) -> tuple[str, str]:
    async with session_factory()() as s:
        live = await s.get(LiveSet, sid)
        root = await s.get(MediaRoot, live.media_root_id)
        outcome = await apply_naming_to_set(s, live, root)
    async with session_factory()() as s:
        return outcome, (await s.get(LiveSet, sid)).audio_path


async def test_renames_to_template(tmp_path: Path):
    ids = await _root(tmp_path)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")

    outcome, audio_path = await _apply(sid)

    assert outcome == "renamed"
    assert audio_path == "Carl-Cox/my-set.flac"
    assert (tmp_path / "Carl-Cox/my-set.flac").read_bytes() == b"AUDIO"
    assert not (tmp_path / "originals/x/upload.flac").exists()
    # The emptied per-set originals dir is tidied away.
    assert not (tmp_path / "originals/x").exists()


async def test_unchanged_returns_unchanged(tmp_path: Path):
    ids = await _root(tmp_path)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="Carl-Cox/my-set.flac")

    outcome, audio_path = await _apply(sid)

    assert outcome == "unchanged"
    assert audio_path == "Carl-Cox/my-set.flac"
    assert (tmp_path / "Carl-Cox/my-set.flac").read_bytes() == b"AUDIO"


async def test_collision_gets_suffix(tmp_path: Path):
    """Two sets render the same path (both have set type "unknown")."""
    ids = await _root(tmp_path, template="{Artist}/{Type}.{Ext}")
    first = await _set(tmp_path, ids, slug="set-a", audio_path="originals/a/a.flac",
                       data=b"FIRST")
    second = await _set(tmp_path, ids, slug="set-b", audio_path="originals/b/b.flac",
                        data=b"SECOND")

    assert await _apply(first) == ("renamed", "Carl-Cox/unknown.flac")
    assert await _apply(second) == ("renamed", "Carl-Cox/unknown (2).flac")

    assert (tmp_path / "Carl-Cox/unknown.flac").read_bytes() == b"FIRST"
    assert (tmp_path / "Carl-Cox/unknown (2).flac").read_bytes() == b"SECOND"
    # Re-applying is stable: the first set keeps its name, the second keeps
    # its suffixed name rather than bouncing to (3).
    assert await _apply(first) == ("unchanged", "Carl-Cox/unknown.flac")
    assert await _apply(second) == ("unchanged", "Carl-Cox/unknown (2).flac")


async def test_collision_with_untracked_file_on_disk(tmp_path: Path):
    """A file no set references still is never overwritten."""
    ids = await _root(tmp_path)
    stray = tmp_path / "Carl-Cox/my-set.flac"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"STRAY")
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")

    assert await _apply(sid) == ("renamed", "Carl-Cox/my-set (2).flac")
    assert stray.read_bytes() == b"STRAY"
    assert (tmp_path / "Carl-Cox/my-set (2).flac").read_bytes() == b"AUDIO"


async def test_collision_with_path_another_set_references(tmp_path: Path):
    """The target name is taken in the DB by another set even though the file
    is missing on disk: still suffixed, the other set's path is not reused."""
    ids = await _root(tmp_path)
    await _set(tmp_path, ids, slug="other", audio_path="Carl-Cox/my-set.flac", data=None)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")

    assert await _apply(sid) == ("renamed", "Carl-Cox/my-set (2).flac")


async def test_old_name_kept_when_in_use(tmp_path: Path):
    ids = await _root(tmp_path)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")
    # Another set (e.g. a recycled copy after an upgrade) names the same file.
    await _set(tmp_path, ids, slug="other", audio_path="originals/x/upload.flac", data=None)

    outcome, audio_path = await _apply(sid)

    assert (outcome, audio_path) == ("renamed", "Carl-Cox/my-set.flac")
    assert (tmp_path / "originals/x/upload.flac").read_bytes() == b"AUDIO"
    assert (tmp_path / "Carl-Cox/my-set.flac").read_bytes() == b"AUDIO"


async def test_no_template_skipped(tmp_path: Path):
    ids = await _root(tmp_path, template=None)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")

    assert await _apply(sid) == ("skipped", "originals/x/upload.flac")
    assert (tmp_path / "originals/x/upload.flac").read_bytes() == b"AUDIO"


async def test_missing_source_skipped(tmp_path: Path):
    ids = await _root(tmp_path)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac",
                     data=None)

    assert await _apply(sid) == ("skipped", "originals/x/upload.flac")
    assert not (tmp_path / "Carl-Cox").exists()


async def test_commit_failure_keeps_old_file(tmp_path: Path, monkeypatch):
    ids = await _root(tmp_path)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")

    async with session_factory()() as s:
        live = await s.get(LiveSet, sid)
        root = await s.get(MediaRoot, live.media_root_id)

        async def broken_commit():
            raise RuntimeError("db down")

        monkeypatch.setattr(s, "commit", broken_commit)
        with pytest.raises(RuntimeError):
            await apply_naming_to_set(s, live, root)

    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).audio_path == "originals/x/upload.flac"
    # The old name is only ever removed after a successful commit.
    assert (tmp_path / "originals/x/upload.flac").read_bytes() == b"AUDIO"


async def test_apply_naming_one_job(tmp_path: Path):
    ids = await _root(tmp_path)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")

    assert await apply_naming_one(str(sid)) == "renamed"
    assert await apply_naming_one(str(sid)) == "unchanged"
    assert await apply_naming_one(str(uuid.uuid4())) == "skipped"
    assert await apply_naming_one("not-a-uuid") == "skipped"


@pytest.mark.parametrize("template", [TEMPLATE, None])
async def test_publish_enqueues_naming_when_template(tmp_path: Path, monkeypatch, template):
    from setvault_core.jobs import ready

    calls: list[uuid.UUID] = []
    monkeypatch.setattr(ready, "enqueue_apply_naming", calls.append)
    ids = await _root(tmp_path, template=template)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")

    async with session_factory()() as s:
        live = await s.get(LiveSet, sid)
        live.status = "processing"
        await ready.publish_live_set(s, live)
        await s.commit()

    assert calls == ([sid] if template else [])


async def test_name_taken_after_check_is_never_overwritten(tmp_path: Path, monkeypatch):
    """Another worker creates the target between the free-name check and the
    placement: the existing file keeps its bytes and the set moves on to the
    next suffix."""
    from setvault_core.jobs import apply_naming

    ids = await _root(tmp_path)
    sid = await _set(tmp_path, ids, slug="my-set", audio_path="originals/x/upload.flac")
    racer = tmp_path / "Carl-Cox/my-set.flac"
    racer.parent.mkdir(parents=True)
    racer.write_bytes(b"OTHER-WORKER")

    real_is_taken = apply_naming._is_taken

    async def stale_check(session, live, root, candidate):
        # The check ran before the other worker created the file.
        if candidate == "Carl-Cox/my-set.flac":
            return False
        return await real_is_taken(session, live, root, candidate)

    monkeypatch.setattr(apply_naming, "_is_taken", stale_check)

    assert await _apply(sid) == ("renamed", "Carl-Cox/my-set (2).flac")
    assert racer.read_bytes() == b"OTHER-WORKER"
    assert (tmp_path / "Carl-Cox/my-set (2).flac").read_bytes() == b"AUDIO"
    assert not (tmp_path / "originals/x/upload.flac").exists()

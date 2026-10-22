"""Tests for the bulk_action job.

The first two are DB-less sanity checks of the RQ entry point. The rest run
against the test database with tmp_path media roots and cover move_root's
file handling and the per-item commit.
"""
from __future__ import annotations

import inspect
import os
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import bulk_action as bulk_mod
from setvault_core.jobs.bulk_action import (
    bulk_action,
    run_bulk_action,
)
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.services.passwords import hash_password


def test_run_bulk_action_is_sync_wrapper():
    """The RQ entry point must be plain (not async) so workers can call it."""
    assert not inspect.iscoroutinefunction(run_bulk_action)
    assert inspect.iscoroutinefunction(bulk_action)


def test_run_bulk_action_signature_takes_keyword_args():
    """The endpoint enqueues with keyword args; the entry point must accept them."""
    sig = inspect.signature(run_bulk_action)
    expected = {"action", "set_ids", "params", "actor_user_id"}
    assert expected <= set(sig.parameters)


# ---------------------------------------------------------------------------
# DB-backed tests (tmp_path media roots)
# ---------------------------------------------------------------------------

FILES = {
    "audio_path": ("audio/set.flac", b"A" * 4096),
    "streaming_path": ("stream/set.opus", b"S" * 1024),
    "waveform_path": ("waveform/set.json", b"W" * 300),
    "thumb_path": ("thumb/set.jpg", b"T" * 200),
}


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


def _mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


async def _root(host: Path, *, enabled: bool = True) -> uuid.UUID:
    _mkdir(host)
    async with session_factory()() as s:
        r = MediaRoot(name=f"r-{uuid.uuid4().hex[:8]}", host_path=str(host), enabled=enabled)
        s.add(r)
        await s.commit()
        return r.id


async def _user() -> uuid.UUID:
    async with session_factory()() as s:
        u = User(email=f"u-{uuid.uuid4().hex[:8]}@x.test", username=f"u{uuid.uuid4().hex[:8]}",
                 display_name="u", password_hash=hash_password("aaaaaaaa"))
        s.add(u)
        await s.commit()
        return u.id


async def _set(root_id: uuid.UUID, host: Path, user_id: uuid.UUID, *,
               prefix: str = "", write: bool = True, paths: dict | None = None) -> uuid.UUID:
    rels = {}
    for col, (rel, data) in (paths or FILES).items():
        rel = f"{prefix}{rel}"
        rels[col] = rel
        if write:
            p = host / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    async with session_factory()() as s:
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                       status="published", source_type="upload", uploaded_by=user_id, **rels)
        s.add(live)
        await s.commit()
        return live.id


async def _get(live_id: uuid.UUID) -> LiveSet:
    async with session_factory()() as s:
        return await s.get(LiveSet, live_id)


async def _move(set_ids, target_id) -> dict:
    return await bulk_action(
        action="move_root", set_ids=[str(i) for i in set_ids],
        params={"target_media_root_id": str(target_id)}, actor_user_id=None,
    )


def _tree(p: Path) -> dict[str, bytes]:
    if not p.exists():
        return {}
    return {f.relative_to(p).as_posix(): f.read_bytes() for f in p.rglob("*") if f.is_file()}


async def test_move_root_moves_all_files(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    ra, rb = await _root(a), await _root(b)
    uid = await _user()
    sid = await _set(ra, a, uid)
    res = await _move([sid], rb)
    live = await _get(sid)
    assert live.media_root_id == rb
    for rel, data in FILES.values():
        dst = b / rel
        assert dst.is_file()
        assert dst.stat().st_size == len(data)
        assert dst.read_bytes() == data
        assert not (a / rel).exists()
    assert res["moved"] == [live.slug]
    assert res["errors"] == 0


async def test_move_root_skips_set_already_on_target(tmp_path):
    a = tmp_path / "A"
    ra = await _root(a)
    uid = await _user()
    sid = await _set(ra, a, uid)
    before = _tree(a)
    res = await _move([sid], ra)
    live = await _get(sid)
    assert res["errors"] == 0
    assert res["skipped"] == [live.slug]
    assert live.media_root_id == ra
    assert _tree(a) == before


@pytest.mark.parametrize("layout", ["same", "target_inside", "source_inside"])
async def test_move_root_refuses_same_or_nested_root(tmp_path, layout):
    a = tmp_path / "A"
    if layout == "same":
        b_host = a
    elif layout == "target_inside":
        b_host = a / "nested"
    else:
        a = tmp_path / "outer" / "A"
        b_host = tmp_path / "outer"
    ra = await _root(a)
    rb = await _root(b_host)
    uid = await _user()
    sid = await _set(ra, a, uid)
    before = _tree(a)
    res = await _move([sid], rb)
    live = await _get(sid)
    assert res["errors"] == 1
    assert res["failed"][0]["slug"] == live.slug
    assert live.media_root_id == ra
    assert _tree(a) == before
    if layout == "target_inside":
        assert _tree(b_host) == {}


async def test_move_root_missing_source_skips_set(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    ra, rb = await _root(a), await _root(b)
    uid = await _user()
    sid = await _set(ra, a, uid)
    (a / FILES["waveform_path"][0]).unlink()
    before = _tree(a)
    res = await _move([sid], rb)
    live = await _get(sid)
    assert res["errors"] == 1
    assert res["failed"][0]["slug"] == live.slug
    assert live.media_root_id == ra
    assert _tree(a) == before
    assert _tree(b) == {}


async def test_move_root_never_overwrites_existing_destination(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    ra, rb = await _root(a), await _root(b)
    uid = await _user()
    sid = await _set(ra, a, uid)
    clash = b / FILES["thumb_path"][0]
    clash.parent.mkdir(parents=True)
    clash.write_bytes(b"precious")
    before = _tree(a)
    res = await _move([sid], rb)
    live = await _get(sid)
    assert res["errors"] == 1
    assert live.media_root_id == ra
    assert clash.read_bytes() == b"precious"
    assert _tree(b) == {FILES["thumb_path"][0]: b"precious"}
    assert _tree(a) == before


async def test_move_root_keeps_old_file_used_by_other_set(tmp_path):
    """Review Focus 4: another set on A references the same file, so A's copy
    stays. A watch-folder name hardlinked to it is never touched."""
    a, b, watch = tmp_path / "A", tmp_path / "B", tmp_path / "watch"
    ra, rb = await _root(a), await _root(b)
    uid = await _user()
    sid = await _set(ra, a, uid)
    watch.mkdir()
    os.link(a / FILES["audio_path"][0], watch / "incoming.flac")
    other = await _set(ra, a, uid, write=False, paths={"audio_path": FILES["audio_path"]})
    res = await _move([sid], rb)
    assert res["errors"] == 0
    assert (await _get(sid)).media_root_id == rb
    assert (await _get(other)).media_root_id == ra
    assert (a / FILES["audio_path"][0]).read_bytes() == FILES["audio_path"][1]
    assert not (a / FILES["thumb_path"][0]).exists()
    assert (b / FILES["audio_path"][0]).read_bytes() == FILES["audio_path"][1]
    assert (watch / "incoming.flac").read_bytes() == FILES["audio_path"][1]


async def test_move_root_keeps_old_file_used_via_alias_root(tmp_path):
    """A second MediaRoot row with the same host_path counts as 'in use' too."""
    a, b = tmp_path / "A", tmp_path / "B"
    ra, rb = await _root(a), await _root(b)
    alias = await _root(a)
    uid = await _user()
    sid = await _set(ra, a, uid)
    await _set(alias, a, uid, write=False, paths={"audio_path": FILES["audio_path"]})
    res = await _move([sid], rb)
    assert res["errors"] == 0
    assert (a / FILES["audio_path"][0]).is_file()
    assert not (a / FILES["thumb_path"][0]).exists()


async def test_move_root_failure_cleans_partial_copies(tmp_path, monkeypatch):
    a, b = tmp_path / "A", tmp_path / "B"
    ra, rb = await _root(a), await _root(b)
    uid = await _user()
    sid = await _set(ra, a, uid)
    before = _tree(a)
    real = bulk_mod.place_audio_file
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(bulk_mod, "place_audio_file", flaky)
    res = await _move([sid], rb)
    assert calls["n"] == 3
    assert res["errors"] == 1
    assert (await _get(sid)).media_root_id == ra
    assert _tree(a) == before
    assert _tree(b) == {}


async def test_move_root_size_mismatch_cleans_up(tmp_path, monkeypatch):
    a, b = tmp_path / "A", tmp_path / "B"
    ra, rb = await _root(a), await _root(b)
    uid = await _user()
    sid = await _set(ra, a, uid)
    before = _tree(a)

    def truncating(src, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(Path(src).read_bytes()[:-1])
        return "copied"

    monkeypatch.setattr(bulk_mod, "place_audio_file", truncating)
    res = await _move([sid], rb)
    assert res["errors"] == 1
    assert (await _get(sid)).media_root_id == ra
    assert _tree(a) == before
    assert _tree(b) == {}


async def test_bulk_commits_per_item(tmp_path, monkeypatch):
    a, b = tmp_path / "A", tmp_path / "B"
    ra, rb = await _root(a), await _root(b)
    uid = await _user()
    s1 = await _set(ra, a, uid, prefix="one/")
    s2 = await _set(ra, a, uid, prefix="two/")
    (a / "two" / FILES["audio_path"][0]).unlink()
    res = await _move([s1, s2], rb)
    assert res["errors"] == 1
    assert (await _get(s1)).media_root_id == rb
    assert (await _get(s2)).media_root_id == ra

    # soft_delete: an exception on the second item must not undo the first.
    real = bulk_mod._soft_delete_one
    calls = {"n": 0}

    async def flaky(s, live, *, actor_id):
        calls["n"] += 1
        await real(s, live, actor_id=actor_id)
        if calls["n"] == 2:
            raise RuntimeError("boom")

    monkeypatch.setattr(bulk_mod, "_soft_delete_one", flaky)
    res = await bulk_action(action="soft_delete", set_ids=[str(s1), str(s2)],
                            params={}, actor_user_id=None)
    assert res["processed"] == 1
    assert res["errors"] == 1
    assert (await _get(s1)).deleted_at is not None
    assert (await _get(s2)).deleted_at is None


async def test_move_root_refuses_disabled_target(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    ra = await _root(a)
    rb = await _root(b, enabled=False)
    uid = await _user()
    sid = await _set(ra, a, uid)
    before = _tree(a)
    res = await _move([sid], rb)
    assert "reason" in res
    assert (await _get(sid)).media_root_id == ra
    assert _tree(a) == before
    assert _tree(b) == {}


async def test_move_root_refuses_unreachable_target(tmp_path):
    a = tmp_path / "A"
    ra = await _root(a)
    async with session_factory()() as s:
        r = MediaRoot(name=f"r-{uuid.uuid4().hex[:8]}", host_path=str(tmp_path / "gone"))
        s.add(r)
        await s.commit()
        rb = r.id
    uid = await _user()
    sid = await _set(ra, a, uid)
    before = _tree(a)
    res = await _move([sid], rb)
    assert "reason" in res
    assert (await _get(sid)).media_root_id == ra
    assert _tree(a) == before
    assert not (tmp_path / "gone").exists()

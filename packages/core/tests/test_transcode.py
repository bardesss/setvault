import asyncio
import logging
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import transcode
from setvault_core.jobs.transcode import transcode_audio
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.services.set_upgrade import _AUDIO_FIELDS
from setvault_core.services.system_config import get_config
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def test_transcode_produces_opus_stream(tmp_path: Path, require_tools):
    require_tools("ffmpeg")
    src = tmp_path / "audio.flac"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-t", "3", str(src)]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: ASYNC221, S603
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="audio.flac", uploaded_by=u.id, source_type="upload",
                       status="processing", duration_seconds=3)
        s.add(live)
        await s.commit()
        sid = live.id

    await transcode_audio(str(sid))

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.streaming_path == f"stream/{sid}.opus"
        out = tmp_path / row.streaming_path
        assert out.exists() and out.stat().st_size > 0


async def _seed_set(tmp_path: Path, normalized_lufs: float | None) -> uuid.UUID:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="audio.flac", uploaded_by=u.id, source_type="upload",
                       status="processing", normalized_lufs=normalized_lufs)
        s.add(live)
        await s.commit()
        return live.id


@pytest.fixture
async def loudness_target():
    """Set the SystemConfig loudness target for one test, then restore it."""
    async with session_factory()() as s:
        before = (await get_config(s)).loudness_target_lufs
        await s.commit()

    async def _set(value: float | None) -> None:
        async with session_factory()() as s:
            (await get_config(s)).loudness_target_lufs = value
            await s.commit()

    yield _set
    await _set(before)


def _fake_ffmpeg(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def _run(args, **kwargs):
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"opus")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _run)
    return calls


async def test_transcode_applies_gain_filter(tmp_path: Path, monkeypatch, loudness_target):
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    calls = _fake_ffmpeg(monkeypatch)

    await transcode_audio(str(sid))

    (args,) = calls
    assert args[args.index("-af") + 1] == "volume=-6.0dB"
    assert (tmp_path / f"stream/{sid}.opus").read_bytes() == b"opus"
    assert not (tmp_path / f"stream/{sid}.opus.tmp").exists()
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).stream_gain_db == -6.0


async def test_transcode_boost_adds_limiter(tmp_path: Path, monkeypatch, loudness_target):
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-20.0)
    calls = _fake_ffmpeg(monkeypatch)

    await transcode_audio(str(sid))

    (args,) = calls
    assert args[args.index("-af") + 1] == "volume=6.0dB,alimiter=limit=0.891:level=false"
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).stream_gain_db == 6.0


async def test_transcode_no_filter_when_target_off(tmp_path: Path, monkeypatch, loudness_target):
    await loudness_target(None)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    calls = _fake_ffmpeg(monkeypatch)

    await transcode_audio(str(sid))

    (args,) = calls
    assert "-af" not in args
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).stream_gain_db == 0.0


async def _seed_swapped_pair(tmp_path: Path) -> tuple[uuid.UUID, uuid.UUID]:
    """A quality upgrade's aftermath: the target streams from the arrival's
    file and the recycled arrival row names ``stream/<target-id>.opus``."""
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        target_id, arrival_id = uuid.uuid4(), uuid.uuid4()
        common = {"media_root_id": r.id, "uploaded_by": u.id, "source_type": "upload",
                  "normalized_lufs": -8.0}
        s.add_all([
            LiveSet(id=target_id, slug=f"s-{uuid.uuid4().hex[:6]}", title="target",
                    audio_path="new.flac", status="published",
                    streaming_path=f"stream/{arrival_id}.opus", **common),
            LiveSet(id=arrival_id, slug=f"s-{uuid.uuid4().hex[:6]}", title="recycled",
                    audio_path="old.flac", status="draft", deleted_at=datetime.now(UTC),
                    streaming_path=f"stream/{target_id}.opus", **common),
        ])
        await s.commit()
    (tmp_path / "stream").mkdir()
    (tmp_path / f"stream/{arrival_id}.opus").write_bytes(b"target-old")
    (tmp_path / f"stream/{target_id}.opus").write_bytes(b"recycled")
    return target_id, arrival_id


async def test_regain_after_upgrade_keeps_recycled_stream(
    tmp_path: Path, monkeypatch, loudness_target,
):
    await loudness_target(-14.0)
    target_id, arrival_id = await _seed_swapped_pair(tmp_path)
    _fake_ffmpeg(monkeypatch)

    # What "Re-apply to library" runs per set (calling regain_library itself
    # would re-transcode every published set in the shared test database).
    await transcode_audio(str(target_id))

    assert (tmp_path / f"stream/{target_id}.opus").read_bytes() == b"recycled"
    async with session_factory()() as s:
        target = await s.get(LiveSet, target_id)
        assert target.stream_gain_db == -6.0
        assert (tmp_path / target.streaming_path).read_bytes() == b"opus"
        referenced = {target.streaming_path, (await s.get(LiveSet, arrival_id)).streaming_path}
    on_disk = {f"stream/{p.name}" for p in (tmp_path / "stream").iterdir()}
    assert on_disk == referenced  # no orphan, no tmp


async def test_transcode_shared_stream_gets_fresh_file(
    tmp_path: Path, monkeypatch, loudness_target,
):
    """Another row names the very file this set streams from: write a fresh
    file and leave the shared one alone."""
    await loudness_target(-14.0)
    target_id, arrival_id = await _seed_swapped_pair(tmp_path)
    async with session_factory()() as s:
        (await s.get(LiveSet, arrival_id)).streaming_path = f"stream/{arrival_id}.opus"
        await s.commit()
    _fake_ffmpeg(monkeypatch)

    await transcode_audio(str(target_id))

    assert (tmp_path / f"stream/{arrival_id}.opus").read_bytes() == b"target-old"
    async with session_factory()() as s:
        path = (await s.get(LiveSet, target_id)).streaming_path
    assert path.startswith(f"stream/{target_id}-") and path.endswith(".opus")
    assert (tmp_path / path).read_bytes() == b"opus"


async def _seed_upgrade_pair(tmp_path: Path) -> tuple[uuid.UUID, uuid.UUID]:
    """Before a quality upgrade: the target streams its old audio from
    ``stream/<target-id>.opus``; the processed arrival has its own stream."""
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        target_id, arrival_id = uuid.uuid4(), uuid.uuid4()
        common = {"media_root_id": r.id, "uploaded_by": u.id, "source_type": "upload"}
        s.add_all([
            LiveSet(id=target_id, slug=f"s-{uuid.uuid4().hex[:6]}", title="target",
                    audio_path="old.flac", status="published", normalized_lufs=-8.0,
                    streaming_path=f"stream/{target_id}.opus", stream_gain_db=-6.0,
                    **common),
            LiveSet(id=arrival_id, slug=f"s-{uuid.uuid4().hex[:6]}", title="arrival",
                    audio_path="new.flac", status="draft", normalized_lufs=-12.0,
                    streaming_path=f"stream/{arrival_id}.opus", stream_gain_db=-2.0,
                    **common),
        ])
        await s.commit()
    (tmp_path / "stream").mkdir()
    (tmp_path / f"stream/{target_id}.opus").write_bytes(b"target-old")
    (tmp_path / f"stream/{arrival_id}.opus").write_bytes(b"arrival")
    return target_id, arrival_id


async def _swap_audio(target_id: uuid.UUID, arrival_id: uuid.UUID) -> None:
    """What apply_upgrade commits: the audio columns change hands and the
    arrival becomes the recycled old copy (separate session and commit)."""
    async with session_factory()() as s:
        rows = (await s.execute(
            select(LiveSet).where(LiveSet.id.in_([target_id, arrival_id]))
            .with_for_update(of=LiveSet)
        )).scalars().all()
        target, arrival = sorted(rows, key=lambda r: r.id != target_id)
        for f in _AUDIO_FIELDS:
            old = getattr(target, f)
            setattr(target, f, getattr(arrival, f))
            setattr(arrival, f, old)
        arrival.deleted_at = datetime.now(UTC)
        await s.commit()


def _ffmpeg_with_side_effect(monkeypatch, side_effect) -> list[list[str]]:
    """Fake ffmpeg that writes its output, then runs ``side_effect(n)`` (n is
    the 1-based call number; returns a coroutine or None) on the test's event
    loop while the encode is still in flight."""
    loop = asyncio.get_running_loop()
    calls: list[list[str]] = []

    def _run(args, **kwargs):
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"opus")
        coro = side_effect(len(calls))
        if coro is not None:
            asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=30)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _run)
    return calls


def _first_call(make_coro):
    return lambda n: make_coro() if n == 1 else None


def _src(args: list[str]) -> str:
    return args[args.index("-i") + 1]


async def _rename_audio(set_id: uuid.UUID, new_rel: str) -> None:
    """What apply_naming_to_set commits: only audio_path changes."""
    async with session_factory()() as s:
        (await s.get(LiveSet, set_id)).audio_path = new_rel
        await s.commit()


async def test_transcode_racing_upgrade_swap_discards_its_stream(
    tmp_path: Path, monkeypatch, loudness_target,
):
    """An upgrade swap commits while the transcode encodes: the transcode
    must not overwrite the recycled row's stream nor revert the target."""
    await loudness_target(-14.0)
    target_id, arrival_id = await _seed_upgrade_pair(tmp_path)
    calls = _ffmpeg_with_side_effect(
        monkeypatch, _first_call(lambda: _swap_audio(target_id, arrival_id)),
    )

    assert await transcode_audio(str(target_id)) == "discarded"  # no exception escapes

    assert len(calls) == 1
    # The recycled row (now naming stream/<target-id>.opus) keeps its bytes.
    assert (tmp_path / f"stream/{target_id}.opus").read_bytes() == b"target-old"
    assert (tmp_path / f"stream/{arrival_id}.opus").read_bytes() == b"arrival"
    async with session_factory()() as s:
        target = await s.get(LiveSet, target_id)
        recycled = await s.get(LiveSet, arrival_id)
        assert target.audio_path == "new.flac"
        assert target.streaming_path == f"stream/{arrival_id}.opus"  # not reverted
        assert target.stream_gain_db == -2.0
        assert recycled.streaming_path == f"stream/{target_id}.opus"
        referenced = {target.streaming_path, recycled.streaming_path}
    on_disk = {f"stream/{p.name}" for p in (tmp_path / "stream").iterdir()}
    assert on_disk == referenced  # no orphan, no temp file


async def test_transcode_audio_renamed_mid_encode_reencodes(
    tmp_path: Path, monkeypatch, loudness_target,
):
    """A rename (audio_path only) lands during a re-transcode: the stream is
    encoded again from the new path and swapped in."""
    await loudness_target(-14.0)
    target_id, _ = await _seed_upgrade_pair(tmp_path)
    calls = _ffmpeg_with_side_effect(
        monkeypatch, _first_call(lambda: _rename_audio(target_id, "renamed.flac")),
    )

    assert await transcode_audio(str(target_id)) == "done"

    assert [_src(c) for c in calls] == [str(tmp_path / "old.flac"), str(tmp_path / "renamed.flac")]
    assert (tmp_path / f"stream/{target_id}.opus").read_bytes() == b"opus"
    async with session_factory()() as s:
        row = await s.get(LiveSet, target_id)
        assert row.streaming_path == f"stream/{target_id}.opus"
        assert row.stream_gain_db == -6.0
    assert not [p for p in (tmp_path / "stream").iterdir() if p.name.endswith(".tmp")]


async def test_transcode_first_encode_survives_rename(
    tmp_path: Path, monkeypatch, loudness_target,
):
    """A new set (no stream yet) renamed mid-encode still ends with a
    committed stream, from the new path."""
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    calls = _ffmpeg_with_side_effect(
        monkeypatch, _first_call(lambda: _rename_audio(sid, "originals/renamed.flac")),
    )

    assert await transcode_audio(str(sid)) == "done"

    assert _src(calls[-1]) == str(tmp_path / "originals/renamed.flac")
    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.streaming_path == f"stream/{sid}.opus"
        assert row.stream_gain_db == -6.0
    assert [p.name for p in (tmp_path / "stream").iterdir()] == [f"{sid}.opus"]


async def test_transcode_first_encode_survives_move_root(
    tmp_path: Path, monkeypatch, loudness_target,
):
    """Move-root lands mid-encode (files moved, media_root_id changed): the
    stream is encoded again and written on the new root only."""
    await loudness_target(-14.0)
    old_host, new_host = tmp_path / "old", tmp_path / "new"
    old_host.mkdir()
    new_host.mkdir()
    sid = await _seed_set(old_host, normalized_lufs=-8.0)
    (old_host / "audio.flac").write_bytes(b"flac")
    async with session_factory()() as s:
        new_root = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(new_host),
                             enabled=True, default_for_ingest=False)
        s.add(new_root)
        await s.commit()
        new_root_id = new_root.id

    async def _move_root() -> None:
        shutil.move(old_host / "audio.flac", new_host / "audio.flac")
        async with session_factory()() as s:
            (await s.get(LiveSet, sid)).media_root_id = new_root_id
            await s.commit()

    calls = _ffmpeg_with_side_effect(monkeypatch, _first_call(_move_root))

    assert await transcode_audio(str(sid)) == "done"

    assert [_src(c) for c in calls] == [
        str(old_host / "audio.flac"), str(new_host / "audio.flac"),
    ]
    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.media_root_id == new_root_id
        assert row.streaming_path == f"stream/{sid}.opus"
    assert (new_host / f"stream/{sid}.opus").read_bytes() == b"opus"
    assert list((old_host / "stream").iterdir()) == []  # no orphan, no temp file


async def test_transcode_gives_up_when_audio_keeps_moving(
    tmp_path: Path, monkeypatch, loudness_target, caplog,
):
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    calls = _ffmpeg_with_side_effect(
        monkeypatch, lambda n: _rename_audio(sid, f"moved-{n}.flac"),
    )

    with caplog.at_level(logging.INFO, logger=transcode.__name__):
        assert await transcode_audio(str(sid)) == "discarded"

    assert len(calls) == transcode.MAX_ATTEMPTS
    messages = [r.getMessage() for r in caplog.records]
    assert sum("re-encoding" in m for m in messages) == transcode.MAX_ATTEMPTS - 1
    assert any("gave up" in m for m in messages)
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).streaming_path is None
    assert list((tmp_path / "stream").iterdir()) == []


async def test_transcode_skips_recycled_set(tmp_path: Path, monkeypatch, loudness_target):
    """A recycled set needs no new stream (purge may be removing its files)."""
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    async with session_factory()() as s:
        (await s.get(LiveSet, sid)).deleted_at = datetime.now(UTC)
        await s.commit()
    calls = _fake_ffmpeg(monkeypatch)

    assert await transcode_audio(str(sid)) == "discarded"

    assert calls == []
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).streaming_path is None


async def test_transcode_set_recycled_mid_encode_discards(
    tmp_path: Path, monkeypatch, loudness_target,
):
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)

    async def _recycle() -> None:
        async with session_factory()() as s:
            (await s.get(LiveSet, sid)).deleted_at = datetime.now(UTC)
            await s.commit()

    _ffmpeg_with_side_effect(monkeypatch, _first_call(_recycle))

    assert await transcode_audio(str(sid)) == "discarded"

    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).streaming_path is None
    assert list((tmp_path / "stream").iterdir()) == []


def _force_fresh_stream_name(monkeypatch, tmp_path: Path, sid: uuid.UUID) -> None:
    """The set streams from stream/previous.opus and the transcode writes a
    fresh name, so the post-commit cleanup has a previous file to remove."""
    async def _fresh(s, live):
        return f"stream/{live.id}-fresh.opus"

    monkeypatch.setattr(transcode, "_stream_rel", _fresh)
    (tmp_path / "stream").mkdir()
    (tmp_path / "stream/previous.opus").write_bytes(b"previous")


async def _set_previous_stream(sid: uuid.UUID) -> None:
    async with session_factory()() as s:
        (await s.get(LiveSet, sid)).streaming_path = "stream/previous.opus"
        await s.commit()


async def test_transcode_old_stream_unlink_error_is_logged(
    tmp_path: Path, monkeypatch, loudness_target, caplog,
):
    """A failure to delete the replaced stream (other than missing) is a
    warning: the new stream is already committed."""
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    await _set_previous_stream(sid)
    _force_fresh_stream_name(monkeypatch, tmp_path, sid)
    real_unlink = Path.unlink

    def _unlink(self, missing_ok=False):
        if self.name == "previous.opus":
            raise PermissionError("locked")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _unlink)
    _fake_ffmpeg(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=transcode.__name__):
        assert await transcode_audio(str(sid)) == "done"

    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).streaming_path == f"stream/{sid}-fresh.opus"
    assert (tmp_path / f"stream/{sid}-fresh.opus").read_bytes() == b"opus"
    assert any("previous.opus" in r.getMessage() for r in caplog.records)


async def test_transcode_cleanup_db_error_is_logged(
    tmp_path: Path, monkeypatch, loudness_target, caplog,
):
    """The post-commit path_in_use query failing must not fail the job."""
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    await _set_previous_stream(sid)
    _force_fresh_stream_name(monkeypatch, tmp_path, sid)

    async def _broken(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(transcode, "path_in_use", _broken)
    _fake_ffmpeg(monkeypatch)

    with caplog.at_level(logging.ERROR, logger=transcode.__name__):
        assert await transcode_audio(str(sid)) == "done"

    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).streaming_path == f"stream/{sid}-fresh.opus"
    assert (tmp_path / "stream/previous.opus").exists()
    assert any("cleanup" in r.getMessage() for r in caplog.records)


def test_enqueue_transcode_queues_with_timeout(monkeypatch):
    import rq

    enqueued: list[tuple] = []

    class _Queue:
        def __init__(self, name, connection):
            self.name = name

        def enqueue(self, func, *args, **kwargs):
            enqueued.append((self.name, func, args, kwargs))

    monkeypatch.setattr(rq, "Queue", _Queue)
    sid = uuid.uuid4()

    assert transcode.enqueue_transcode(sid) is True

    assert enqueued == [(
        "default", "setvault_core.jobs.transcode.transcode_audio_sync", (str(sid),),
        {"job_timeout": transcode.TRANSCODE_JOB_TIMEOUT},
    )]


def test_enqueue_transcode_failure_is_logged(monkeypatch, caplog):
    import rq

    def _broken(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(rq, "Queue", _broken)

    with caplog.at_level(logging.ERROR, logger=transcode.__name__):
        assert transcode.enqueue_transcode(uuid.uuid4()) is False

    assert any("enqueue failed" in r.getMessage() for r in caplog.records)


async def test_transcode_no_filter_for_bogus_measurement(
    tmp_path: Path, monkeypatch, loudness_target,
):
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-70.0)
    calls = _fake_ffmpeg(monkeypatch)

    await transcode_audio(str(sid))

    (args,) = calls
    assert "-af" not in args
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).stream_gain_db == 0.0

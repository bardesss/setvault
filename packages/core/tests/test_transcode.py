import asyncio
import logging
import os
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
        for f in ("audio_path", "streaming_path", "normalized_lufs", "stream_gain_db"):
            old = getattr(target, f)
            setattr(target, f, getattr(arrival, f))
            setattr(arrival, f, old)
        arrival.deleted_at = datetime.now(UTC)
        await s.commit()


def _ffmpeg_with_side_effect(monkeypatch, side_effect) -> list[list[str]]:
    """Fake ffmpeg that runs ``side_effect()`` (a coroutine factory) on the
    test's event loop while the encode is in flight, then writes the output."""
    loop = asyncio.get_running_loop()
    calls: list[list[str]] = []

    def _run(args, **kwargs):
        calls.append(list(args))
        Path(args[-1]).write_bytes(b"opus")
        asyncio.run_coroutine_threadsafe(side_effect(), loop).result(timeout=30)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _run)
    return calls


async def test_transcode_racing_upgrade_swap_discards_its_stream(
    tmp_path: Path, monkeypatch, loudness_target,
):
    """An upgrade swap commits while the transcode encodes: the transcode
    must not overwrite the recycled row's stream nor revert the target."""
    await loudness_target(-14.0)
    target_id, arrival_id = await _seed_upgrade_pair(tmp_path)
    calls = _ffmpeg_with_side_effect(monkeypatch, lambda: _swap_audio(target_id, arrival_id))

    await transcode_audio(str(target_id))  # no exception escapes

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


async def test_transcode_audio_replaced_mid_encode_keeps_row(
    tmp_path: Path, monkeypatch, loudness_target,
):
    """The row's audio changes (separate commit) during the encode: the
    stream encoded from the old audio is discarded."""
    await loudness_target(-14.0)
    target_id, _ = await _seed_upgrade_pair(tmp_path)

    async def _replace() -> None:
        async with session_factory()() as s:
            row = await s.get(LiveSet, target_id)
            row.audio_path = "replaced.flac"
            await s.commit()

    _ffmpeg_with_side_effect(monkeypatch, _replace)

    await transcode_audio(str(target_id))

    assert (tmp_path / f"stream/{target_id}.opus").read_bytes() == b"target-old"
    async with session_factory()() as s:
        row = await s.get(LiveSet, target_id)
        assert row.streaming_path == f"stream/{target_id}.opus"
        assert row.stream_gain_db == -6.0
    assert not [p for p in (tmp_path / "stream").iterdir() if p.name.endswith(".tmp")]


async def test_transcode_old_stream_unlink_error_is_logged(
    tmp_path: Path, monkeypatch, loudness_target, caplog,
):
    """A failure to delete the replaced stream (other than missing) is a
    warning: the new stream is already committed."""
    await loudness_target(-14.0)
    sid = await _seed_set(tmp_path, normalized_lufs=-8.0)
    async with session_factory()() as s:
        (await s.get(LiveSet, sid)).streaming_path = "stream/previous.opus"
        await s.commit()
    (tmp_path / "stream").mkdir()
    (tmp_path / "stream/previous.opus").write_bytes(b"previous")

    async def _fresh(s, live):
        return f"stream/{live.id}-fresh.opus"

    monkeypatch.setattr(transcode, "_stream_rel", _fresh)
    real_unlink = Path.unlink

    def _unlink(self, missing_ok=False):
        if self.name == "previous.opus":
            raise PermissionError("locked")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _unlink)
    _fake_ffmpeg(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=transcode.__name__):
        await transcode_audio(str(sid))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).streaming_path == f"stream/{sid}-fresh.opus"
    assert (tmp_path / f"stream/{sid}-fresh.opus").read_bytes() == b"opus"
    assert any("previous.opus" in r.getMessage() for r in caplog.records)


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

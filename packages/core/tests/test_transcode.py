import os
import subprocess
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.transcode import transcode_audio
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.services.system_config import get_config


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

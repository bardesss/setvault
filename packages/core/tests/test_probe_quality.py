import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.probe import probe_audio
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


def _gen(args: list[str]) -> None:
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)  # noqa: S603, S607


async def _seed(tmp_path: Path, src: Path) -> uuid.UUID:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="originals/x", uploaded_by=u.id, source_type="upload",
                       status="processing")
        (tmp_path / "originals").mkdir()
        shutil.copy(src, tmp_path / "originals" / "x")
        s.add(live)
        await s.commit()
        return live.id


async def test_probe_stores_quality(tmp_path, require_tools):
    require_tools("ffmpeg")
    mp3 = tmp_path / "src.mp3"
    _gen(["-v", "error", "-y", "-f", "lavfi", "-i",
          "anoisesrc=color=white:d=5:r=44100", "-c:a", "libmp3lame", "-b:a", "320k", str(mp3)])
    sid = await _seed(tmp_path, mp3)

    await probe_audio(str(sid))

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.quality_tier == "high"
        assert row.audio_codec == "mp3"
        assert row.audio_lossless is False
        assert row.quality_measured_at is not None
        assert row.duration_seconds is not None


async def test_probe_measurement_failure_leaves_quality_null(tmp_path, monkeypatch, require_tools):
    require_tools("ffmpeg")
    from setvault_core.jobs import probe as probe_mod

    def boom(_path):
        raise RuntimeError("nope")

    monkeypatch.setattr(probe_mod, "measure_quality", boom)
    mp3 = tmp_path / "src.mp3"
    _gen(["-v", "error", "-y", "-f", "lavfi", "-i",
          "anoisesrc=color=white:d=3:r=44100", str(mp3)])
    sid = await _seed(tmp_path, mp3)

    await probe_audio(str(sid))

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.quality_tier is None
        assert row.duration_seconds is not None

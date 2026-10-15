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


@pytest.fixture
async def silent_audio(tmp_path: Path, require_tools) -> Path:
    require_tools("ffmpeg")
    out = tmp_path / "silent.flac"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-t", "3", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: ASYNC221, S603
    return out


async def test_probe_writes_duration_to_live_set(silent_audio, tmp_path):
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
        shutil.copy(silent_audio, tmp_path / "originals" / "x")
        s.add(live)
        await s.commit()
        sid = live.id

    await probe_audio(str(sid))

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.duration_seconds is not None
        assert 2 <= row.duration_seconds <= 4

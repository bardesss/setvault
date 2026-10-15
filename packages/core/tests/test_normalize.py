import os
import subprocess
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.normalize import _extract_integrated_loudness, normalize_audio
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def test_normalize_stores_lufs(tmp_path: Path, require_tools):
    require_tools("ffmpeg")
    src = tmp_path / "audio.flac"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           "sine=frequency=1000:duration=3", str(src)]
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

    await normalize_audio(str(sid))

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.normalized_lufs is not None
        assert -40 < row.normalized_lufs < 0


def test_extract_integrated_loudness_reads_summary_not_frame_lines():
    """ebur128 logs a running ``I: -70.0 LUFS`` on every frame before the
    summary; only the summary's integrated value is the real loudness."""
    stderr = (
        "[Parsed_ebur128_0 @ 0x1] t: 0.0999773  TARGET:-23 LUFS    M:-120.7 S:-120.7"
        "     I: -70.0 LUFS       LRA:   0.0 LU  FTPK: -18.1 dBFS  TPK: -18.1 dBFS\n"
        "[Parsed_ebur128_0 @ 0x1] t: 2.99998    TARGET:-23 LUFS    M: -21.1 S:-120.7"
        "     I: -21.2 LUFS       LRA:   0.0 LU  FTPK: -18.1 dBFS  TPK: -18.1 dBFS\n"
        "[Parsed_ebur128_0 @ 0x1] Summary:\n"
        "\n"
        "  Integrated loudness:\n"
        "    I:         -21.1 LUFS\n"
        "    Threshold: -31.1 LUFS\n"
    )
    assert _extract_integrated_loudness(stderr) == -21.1

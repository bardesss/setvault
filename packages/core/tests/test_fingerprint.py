import os
import subprocess
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.fingerprint import fingerprint_audio
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.identity import User
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
def fpcalc_present(require_tools):
    require_tools("fpcalc")


async def test_fingerprint_stores_hash(tmp_path: Path, fpcalc_present, require_tools):
    require_tools("ffmpeg")
    audio = tmp_path / "audio.flac"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-t", "3", str(audio)]
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

    await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        rows = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == sid),
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].fingerprint_hash


async def _make_set(tmp_path: Path) -> uuid.UUID:
    (tmp_path / "audio.flac").write_bytes(b"not really flac")
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
        return live.id


def _fake_fpcalc(monkeypatch, returncode: int, stdout: str) -> None:
    def fake_run(args, check=False, **_kwargs):
        proc = subprocess.CompletedProcess(
            args, returncode, stdout=stdout,
            stderr="ERROR: Error decoding audio frame (End of file)\n",
        )
        if check:
            proc.check_returncode()
        return proc
    monkeypatch.setattr("setvault_core.jobs.fingerprint.subprocess.run", fake_run)


async def test_fingerprint_accepts_fpcalc_eof_exit_code(tmp_path: Path, monkeypatch):
    """chromaprint 1.5.1 (Debian bookworm, Ubuntu noble) exits 3 at end of file
    even though it printed a valid fingerprint. That must not fail ingest."""
    sid = await _make_set(tmp_path)
    _fake_fpcalc(monkeypatch, 3, '{"duration": 3.00, "fingerprint": "AQAAZEqSSEoS"}\n')

    await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        rows = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == sid),
        )).scalars().all()
        assert len(rows) == 1


async def test_fingerprint_raises_when_fpcalc_prints_nothing(tmp_path: Path, monkeypatch):
    sid = await _make_set(tmp_path)
    _fake_fpcalc(monkeypatch, 3, "")

    with pytest.raises(RuntimeError, match="fpcalc failed"):
        await fingerprint_audio(str(sid))

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.jobs.url_rip_job import _error_text, _run_rip_job, _set_status
from setvault_core.models.identity import User
from setvault_core.models.url_rip import RipJob
from setvault_core.services.passwords import hash_password


async def _make_user(session):
    user = User(
        email=f"u-{uuid.uuid4().hex[:6]}@x.test",
        username=f"u{uuid.uuid4().hex[:6]}",
        display_name="u",
        password_hash=hash_password("aaaaaaaa"),
    )
    session.add(user)
    await session.flush()
    return user


def test_error_text_surfaces_subprocess_stderr():
    """A failing ffmpeg/audiowaveform step must surface its stderr, not just
    'returned non-zero exit status 1' — that's what makes a rip debuggable."""
    exc = subprocess.CalledProcessError(
        1, ["audiowaveform", "--input-format", "wav", "-i", "-"],
        stderr=b"Error: Unknown input format\n",
    )
    text = _error_text(exc)
    assert "audiowaveform" in text
    assert "Unknown input format" in text


@pytest.mark.asyncio
async def test_set_status_updates_row(session):
    """_set_status(job, 'downloading', progress_pct=15) mutates the row in place."""
    user = await _make_user(session)
    await session.commit()

    job = RipJob(
        submitted_by=user.id, source_url="https://x", status="queued", progress_pct=0,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()

    await _set_status(session, job, "downloading", progress_pct=15, message="fetching audio")
    assert job.status == "downloading"
    assert job.progress_pct == 15
    assert job.message == "fetching audio"
    assert job.started_at is not None


@pytest.mark.asyncio
async def test_run_rip_job_failure_captures_error(session, monkeypatch):
    """If the download step raises, the job ends in status='failed' with error_text set."""
    from setvault_core.models.catalog import MediaRoot

    user = await _make_user(session)
    root = MediaRoot(
        name=f"r-{uuid.uuid4().hex[:6]}", host_path="/srv/test-media",
        default_for_ingest=True,
    )
    session.add(root)
    await session.commit()

    job = RipJob(
        submitted_by=user.id, source_url="https://x", status="queued", progress_pct=0,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(job)
    await session.commit()
    job_id = job.id

    async def _boom(*a, **kw):
        raise RuntimeError("yt-dlp boom")

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _boom)

    await _run_rip_job(session, job_id)
    await session.refresh(job)
    assert job.status == "failed"
    # This is a self-hosted single-user app: surface the real exception (type +
    # message) so failures are debuggable from the UI. Full traceback still goes
    # to the worker log.
    assert "yt-dlp boom" in (job.error_text or "")
    assert "RuntimeError" in (job.error_text or "")


async def _make_root(session, tmp_path):
    from setvault_core.models.catalog import MediaRoot

    root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                     default_for_ingest=True)
    session.add(root)
    await session.commit()


async def _queued_rip(session, user):
    job = RipJob(
        submitted_by=user.id, source_url="https://x.bandcamp.com/track/t", status="queued",
        progress_pct=0, probed_metadata={"title": "Rip"},
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(job)
    await session.commit()
    return job.id


def _fake_download(src):
    import shutil

    async def _download(job, tmp_dir):
        dst = tmp_dir / f"{job.id}.flac"
        shutil.copy(src, dst)
        return dst
    return _download


@pytest.mark.asyncio
async def test_run_rip_job_fingerprints_between_probe_and_transcode(
    session, monkeypatch, tmp_path,
):
    """Rips get the same chromaprint dedup as uploads: fingerprint runs after
    the download is probed and before any transcode work."""
    src = tmp_path / "src.flac"
    src.write_bytes(b"x")
    user = await _make_user(session)
    await _make_root(session, tmp_path)
    job_id = await _queued_rip(session, user)

    calls: list[str] = []

    def _stage(name):
        async def _run(live_set_id):
            calls.append(name)
        return _run

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _fake_download(src))
    for mod, fn in [("probe", "probe_audio"), ("fingerprint", "fingerprint_audio"),
                    ("transcode", "transcode_audio"), ("normalize", "normalize_audio"),
                    ("waveform", "generate_waveform"), ("ready", "mark_ready")]:
        monkeypatch.setattr(f"setvault_core.jobs.{mod}.{fn}", _stage(fn))

    await _run_rip_job(session, job_id)

    job = await session.get(RipJob, job_id)
    await session.refresh(job)
    assert job.status == "ready", job.error_text
    assert calls == ["probe_audio", "fingerprint_audio", "transcode_audio",
                     "normalize_audio", "generate_waveform", "mark_ready"]


@pytest.mark.asyncio
async def test_rip_of_known_audio_is_flagged_duplicate(
    session, monkeypatch, tmp_path, require_tools,
):
    """Ripping the same audio twice records a SetFingerprint for the first rip
    and points the second at it via duplicate_of."""
    require_tools("ffmpeg", "fpcalc", "audiowaveform")
    from setvault_core.models.catalog import LiveSet, SetFingerprint
    from sqlalchemy import select

    src = tmp_path / "src.flac"
    subprocess.run(  # noqa: ASYNC221, S603
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=523:duration=5",  # noqa: S607
         str(src)],
        check=True, capture_output=True,
    )
    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _fake_download(src))
    user = await _make_user(session)
    await _make_root(session, tmp_path)

    set_ids = []
    for _ in range(2):
        job_id = await _queued_rip(session, user)
        await _run_rip_job(session, job_id)
        job = await session.get(RipJob, job_id)
        await session.refresh(job)
        assert job.status == "ready", job.error_text
        set_ids.append(job.live_set_id)

    first, second = set_ids
    fp = (await session.execute(
        select(SetFingerprint).where(SetFingerprint.live_set_id == first),
    )).scalar_one_or_none()
    assert fp is not None
    dup = await session.get(LiveSet, second)
    await session.refresh(dup)
    assert dup.duplicate_of == first
    # Duplicates are held as drafts for admin review, never auto-published.
    assert dup.status == "draft"


@pytest.mark.asyncio
async def test_download_requests_single_video_with_size_cap(tmp_path):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from setvault_core.jobs.url_rip_job import MAX_DOWNLOAD_BYTES, _download

    out = tmp_path / "x.opus"
    out.write_bytes(b"x")
    ctx = MagicMock()
    ctx.__enter__.return_value.extract_info.return_value = {"filepath": str(out)}
    job = SimpleNamespace(id=uuid.uuid4(), source_url="https://www.youtube.com/watch?v=a&list=PL1")

    with patch("yt_dlp.YoutubeDL", return_value=ctx) as ydl:
        assert await _download(job, tmp_path) == out

    opts = ydl.call_args.args[0]
    assert opts["noplaylist"] is True
    assert opts["max_filesize"] == MAX_DOWNLOAD_BYTES


@pytest.mark.asyncio
async def test_download_aborts_once_written_bytes_pass_the_cap(tmp_path, monkeypatch):
    """max_filesize is only checked when the size is known up front, so the
    cap must also stop a download on the bytes actually written. Served from
    a local HTTP server without Content-Length (like a streamed download)."""
    import threading
    import uuid
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace

    from setvault_core.jobs import url_rip_job

    class _Stream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"  # no Content-Length: size unknown up front

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.end_headers()
            try:
                for _ in range(64):
                    self.wfile.write(b"\0" * 16384)
            except ConnectionError:
                pass  # the client hung up once the cap tripped

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(url_rip_job, "MAX_DOWNLOAD_BYTES", 100_000)
        monkeypatch.setattr(
            "setvault_core.services.url_rip.require_supported_url", lambda _url: None,
        )
        job = SimpleNamespace(
            id=uuid.uuid4(),
            source_url=f"http://127.0.0.1:{server.server_port}/set.wav",
        )
        with pytest.raises(Exception, match="exceeded"):
            await url_rip_job._download(job, tmp_path)
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_download_refuses_a_stream_that_went_live_after_submit(tmp_path):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from setvault_core.jobs.url_rip_job import _download

    def _fake_ydl(opts):
        ctx = MagicMock()

        def _extract(url, download):
            # yt-dlp consults match_filter before downloading.
            assert opts["match_filter"]({"id": "a", "live_status": "is_live"}) is not None
            return None

        ctx.__enter__.return_value.extract_info.side_effect = _extract
        return ctx

    job = SimpleNamespace(id=uuid.uuid4(), source_url="https://www.youtube.com/watch?v=a")
    with patch("yt_dlp.YoutubeDL", side_effect=_fake_ydl), \
            pytest.raises(RuntimeError, match="live streams"):
        await _download(job, tmp_path)


@pytest.mark.asyncio
async def test_failed_rip_leaves_no_orphan_draft_or_files(session, monkeypatch, tmp_path):
    """A rip that fails after the download (here: transcode) must not leave an
    invisible draft LiveSet + its audio behind; a retry would add another."""
    from setvault_core.models.catalog import LiveSet
    from sqlalchemy import select

    src = tmp_path / "src.flac"
    src.write_bytes(b"x")
    user = await _make_user(session)
    await _make_root(session, tmp_path)
    job_id = await _queued_rip(session, user)

    async def _ok(live_set_id):
        return None

    async def _boom(live_set_id):
        raise RuntimeError("ffmpeg boom")

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _fake_download(src))
    for mod, fn in [("probe", "probe_audio"), ("fingerprint", "fingerprint_audio")]:
        monkeypatch.setattr(f"setvault_core.jobs.{mod}.{fn}", _ok)
    monkeypatch.setattr("setvault_core.jobs.transcode.transcode_audio", _boom)

    await _run_rip_job(session, job_id)

    job = await session.get(RipJob, job_id, populate_existing=True)
    assert job.status == "failed"
    assert "ffmpeg boom" in (job.error_text or "")
    assert job.live_set_id is None
    left = (await session.execute(
        select(LiveSet).where(LiveSet.source_type == "url_rip", LiveSet.uploaded_by == user.id),
    )).scalars().all()
    assert left == []
    assert not (tmp_path / "originals" / str(job_id)).exists()


@pytest.mark.asyncio
async def test_rip_skips_a_disabled_default_root(session, monkeypatch, tmp_path):
    from setvault_core.models.catalog import MediaRoot

    user = await _make_user(session)
    session.add(MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                          default_for_ingest=True, enabled=False))
    await session.commit()
    job_id = await _queued_rip(session, user)
    downloaded = False

    async def _download(job, tmp_dir):
        nonlocal downloaded
        downloaded = True

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _download)

    await _run_rip_job(session, job_id)

    job = await session.get(RipJob, job_id, populate_existing=True)
    assert job.status == "failed"
    assert "no default-for-ingest" in (job.error_text or "")
    assert downloaded is False

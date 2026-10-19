from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.jobs.ready import ArrivalResult
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
        async def _run(live_set_id, **kwargs):
            calls.append(name)
            if name == "finish_arrival":
                return ArrivalResult("publish", "published")
        return _run

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _fake_download(src))
    for mod, fn in [("probe", "probe_audio"), ("fingerprint", "fingerprint_audio"),
                    ("transcode", "transcode_audio"), ("normalize", "normalize_audio"),
                    ("waveform", "generate_waveform"), ("ready", "finish_arrival")]:
        monkeypatch.setattr(f"setvault_core.jobs.{mod}.{fn}", _stage(fn))

    await _run_rip_job(session, job_id)

    job = await session.get(RipJob, job_id)
    await session.refresh(job)
    assert job.status == "ready", job.error_text
    assert calls == ["probe_audio", "fingerprint_audio", "transcode_audio",
                     "normalize_audio", "generate_waveform", "finish_arrival"]


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


def test_download_prefers_lossless_but_falls_back_to_bestaudio():
    from setvault_core.jobs.url_rip_job import _AUDIO_FORMAT

    parts = _AUDIO_FORMAT.split("/")
    assert parts[0] == "bestaudio[acodec=flac]"
    assert {"bestaudio[ext=flac]", "bestaudio[acodec=alac]",
            "bestaudio[ext=wav]", "bestaudio[ext=aiff]"} <= set(parts[:6])
    assert parts[-2:] == ["bestaudio", "best"]  # YouTube etc. still get bestaudio


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


async def test_partial_rip_discard_keeps_files_another_set_references(session, tmp_path):
    """R15: _discard_partial_rip removes the rip's files except any another
    LiveSet still points at (e.g. a target this rip's audio was swapped into)."""
    from setvault_core.jobs.url_rip_job import _discard_partial_rip
    from setvault_core.models.catalog import LiveSet, MediaRoot

    user = await _make_user(session)
    root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path=str(tmp_path))
    session.add(root)
    await session.flush()
    job_id = await _queued_rip(session, user)
    job = await session.get(RipJob, job_id)
    keep_rel = f"originals/{job_id}/kept.flac"
    other = LiveSet(slug=f"o-{uuid.uuid4().hex[:6]}", title="other", media_root_id=root.id,
                    audio_path=keep_rel, status="published", source_type="url_rip",
                    uploaded_by=user.id)
    draft = LiveSet(slug=f"d-{uuid.uuid4().hex[:6]}", title="draft", media_root_id=root.id,
                    audio_path=f"originals/{job_id}/gone.flac", status="draft",
                    streaming_path="stream/shared.opus", source_type="url_rip",
                    uploaded_by=user.id)
    session.add_all([other, draft])
    await session.flush()
    other.streaming_path = "stream/shared.opus"
    job.live_set_id = draft.id
    await session.commit()
    for rel in (keep_rel, f"originals/{job_id}/gone.flac", "stream/shared.opus"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")

    await _discard_partial_rip(session, job, root, created_live_set_id=draft.id)

    assert (tmp_path / keep_rel).exists()
    assert (tmp_path / "stream/shared.opus").exists()
    assert not (tmp_path / f"originals/{job_id}/gone.flac").exists()
    assert await session.get(LiveSet, other.id) is not None


async def test_failure_after_a_committed_upgrade_deletes_neither_set(
    session, monkeypatch, tmp_path,
):
    """If the rip fails after apply_upgrade committed (a later step raises),
    the partial-rip cleanup must not hard-delete the upgraded target (which the
    RipJob now points at) or the recycled old copy (the row this rip created)."""
    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet, MediaRoot
    from setvault_core.models.engagement_3c import Comment
    from setvault_core.services import set_upgrade
    from sqlalchemy import select

    async def _no_webhooks(live, event):
        return None

    monkeypatch.setattr(set_upgrade, "fan_out_webhooks", _no_webhooks)
    src = tmp_path / "src.flac"
    src.write_bytes(b"new")
    user = await _make_user(session)
    await _make_root(session, tmp_path)
    root = (await session.execute(select(MediaRoot))).scalars().first()
    tid = uuid.uuid4()
    target = LiveSet(id=tid, slug=f"t-{tid.hex[:6]}", title="Target", media_root_id=root.id,
                     audio_path=f"originals/{tid}/old.mp3", streaming_path=f"stream/{tid}.opus",
                     waveform_path=f"waveform/{tid}.json", status="published",
                     source_type="upload", uploaded_by=user.id, quality_tier="ok")
    session.add(target)
    await session.flush()
    session.add(Comment(live_set_id=tid, user_id=user.id, position_seconds=10, body="hi"))
    await session.commit()
    for rel in (target.audio_path, target.streaming_path, target.waveform_path):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"old")
    job_id = await _queued_rip(session, user)

    async def _ok(live_set_id):
        return None

    async def _swap_then_boom(live_set_id, **kwargs):
        aid = uuid.UUID(live_set_id)
        async with session_factory()() as s:
            arrival = await s.get(LiveSet, aid)
            arrival.streaming_path = f"stream/{aid}.opus"
            arrival.waveform_path = f"waveform/{aid}.json"
            arrival.quality_tier = "lossless"
            await s.commit()
            for rel in (arrival.streaming_path, arrival.waveform_path):
                (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
                (tmp_path / rel).write_bytes(b"new")
            t = await s.get(LiveSet, tid)
            await set_upgrade.apply_upgrade(s, target=t, arrival=arrival, trigger="url_rip")
        raise RuntimeError("boom after swap")

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _fake_download(src))
    for mod, fn in [("probe", "probe_audio"), ("fingerprint", "fingerprint_audio"),
                    ("transcode", "transcode_audio"), ("normalize", "normalize_audio"),
                    ("waveform", "generate_waveform")]:
        monkeypatch.setattr(f"setvault_core.jobs.{mod}.{fn}", _ok)
    monkeypatch.setattr("setvault_core.jobs.ready.finish_arrival", _swap_then_boom)

    await _run_rip_job(session, job_id)

    async with session_factory()() as s:
        job = await s.get(RipJob, job_id)
        assert job.status == "failed"
        t = await s.get(LiveSet, tid)
        assert t is not None and t.deleted_at is None and t.quality_tier == "lossless"
        comments = (await s.execute(select(Comment).where(Comment.live_set_id == tid)))
        assert len(comments.scalars().all()) == 1
        recycled = (await s.execute(select(LiveSet).where(
            LiveSet.id != tid, LiveSet.uploaded_by == user.id))).scalars().all()
        assert len(recycled) == 1 and recycled[0].deleted_at is not None
        assert recycled[0].audio_path == f"originals/{tid}/old.mp3"
        # Both copies' files are still on disk.
        for rel in (t.audio_path, t.streaming_path, t.waveform_path,
                    recycled[0].audio_path, recycled[0].streaming_path):
            assert (tmp_path / rel).exists(), rel


async def _upgrade_rip_setup(
    session, monkeypatch, tmp_path, *, arrival_tier, matches, recycled=False,
):
    """A published MP3 target, an upgrade-attempt rip for it, and stubbed stages:
    the fingerprint stub measures the arrival and flags (or not) the match."""
    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet, MediaRoot
    from setvault_core.services import set_upgrade
    from setvault_core.services.system_config import get_config
    from sqlalchemy import select

    async def _no_webhooks(live, event):
        return None

    monkeypatch.setattr(set_upgrade, "fan_out_webhooks", _no_webhooks)
    cfg = await get_config(session)
    cfg.auto_upgrades_enabled = True
    src = tmp_path / "src.flac"
    src.write_bytes(b"new")
    user = await _make_user(session)
    await _make_root(session, tmp_path)
    root = (await session.execute(
        select(MediaRoot).where(MediaRoot.host_path == str(tmp_path))
    )).scalars().first()
    tid = uuid.uuid4()
    session.add(LiveSet(
        id=tid, slug=f"t-{tid.hex[:6]}", title="Target", media_root_id=root.id,
        audio_path=f"originals/{tid}/old.mp3", streaming_path=f"stream/{tid}.opus",
        waveform_path=f"waveform/{tid}.json", status="published", source_type="upload",
        uploaded_by=user.id, quality_tier="ok", audio_lossless=False,
    ))
    await session.commit()
    job_id = await _queued_rip(session, user)
    job = await session.get(RipJob, job_id)
    job.upgrade_target_set_id = tid
    job.trigger = "scheduled"
    job.source_platform = "bandcamp"
    job.source_external_id = "bc-1"
    await session.commit()

    calls: list[str] = []

    async def _ok(live_set_id):
        return None

    async def _fingerprint(live_set_id, **_kw):
        async with session_factory()() as s:
            live = await s.get(LiveSet, uuid.UUID(live_set_id))
            live.quality_tier = arrival_tier
            live.audio_lossless = arrival_tier == "lossless"
            live.duplicate_of = tid if matches else None
            if recycled:  # as fingerprint does for a match with a recycled original
                live.deleted_at = datetime.now(UTC)
            await s.commit()

    def _track(name):
        async def _run(live_set_id):
            calls.append(name)
            async with session_factory()() as s:
                live = await s.get(LiveSet, uuid.UUID(live_set_id))
                if name == "transcode_audio":
                    live.streaming_path = f"stream/{live.id}.opus"
                if name == "generate_waveform":
                    live.waveform_path = f"waveform/{live.id}.json"
                await s.commit()
        return _run

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _fake_download(src))
    monkeypatch.setattr("setvault_core.jobs.probe.probe_audio", _ok)
    monkeypatch.setattr("setvault_core.jobs.fingerprint.fingerprint_audio", _fingerprint)
    for mod, fn in [("transcode", "transcode_audio"), ("normalize", "normalize_audio"),
                    ("waveform", "generate_waveform")]:
        monkeypatch.setattr(f"setvault_core.jobs.{mod}.{fn}", _track(fn))
    return tid, job_id, user, calls


async def test_upgrade_rip_of_different_audio_is_discarded_before_transcode(
    session, monkeypatch, tmp_path,
):
    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet
    from setvault_core.models.upgrades import SetUpgradeEvent
    from sqlalchemy import select

    tid, job_id, user, calls = await _upgrade_rip_setup(
        session, monkeypatch, tmp_path, arrival_tier="lossless", matches=False,
    )

    await _run_rip_job(session, job_id)

    assert calls == []  # transcode, normalize and waveform never ran
    async with session_factory()() as s:
        job = await s.get(RipJob, job_id)
        assert job.status == "ready", job.error_text
        assert job.message == "no upgrade: different audio"
        assert job.live_set_id is None
        left = (await s.execute(select(LiveSet).where(
            LiveSet.uploaded_by == user.id, LiveSet.id != tid))).scalars().all()
        assert left == []
        [event] = (await s.execute(select(SetUpgradeEvent).where(
            SetUpgradeEvent.live_set_id == tid))).scalars().all()
        assert (event.outcome, event.reason, event.trigger) == (
            "rejected", "different audio", "scheduled")
        assert (event.candidate_source_kind, event.candidate_external_id) == (
            "bandcamp", "bc-1")
    assert not (tmp_path / "originals" / str(job_id)).exists()


async def test_upgrade_rip_of_worse_audio_is_discarded_before_transcode(
    session, monkeypatch, tmp_path,
):
    from setvault_core.db import session_factory

    _tid, job_id, _user, calls = await _upgrade_rip_setup(
        session, monkeypatch, tmp_path, arrival_tier="low", matches=True,
    )

    await _run_rip_job(session, job_id)

    assert calls == []
    async with session_factory()() as s:
        job = await s.get(RipJob, job_id)
        assert job.status == "ready", job.error_text
        assert job.message == "no upgrade: not better"


async def test_upgrade_rip_of_better_audio_upgrades_the_target(
    session, monkeypatch, tmp_path,
):
    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet

    tid, job_id, _user, calls = await _upgrade_rip_setup(
        session, monkeypatch, tmp_path, arrival_tier="lossless", matches=True,
    )

    await _run_rip_job(session, job_id)

    assert calls == ["transcode_audio", "normalize_audio", "generate_waveform"]
    async with session_factory()() as s:
        job = await s.get(RipJob, job_id)
        assert job.status == "ready", job.error_text
        assert job.message.startswith("upgraded")
        assert job.live_set_id == tid
        target = await s.get(LiveSet, tid)
        assert target.quality_tier == "lossless" and target.deleted_at is None


async def test_recycled_upgrade_rip_ends_before_transcode(session, monkeypatch, tmp_path):
    """R1: fingerprinting already recycled the arrival; the rip ends as held
    without the transcode work and keeps the recycled row for the purge job."""
    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet

    tid, job_id, _user, calls = await _upgrade_rip_setup(
        session, monkeypatch, tmp_path, arrival_tier="lossless", matches=True, recycled=True,
    )

    await _run_rip_job(session, job_id)

    assert calls == []
    async with session_factory()() as s:
        job = await s.get(RipJob, job_id)
        assert job.status == "ready", job.error_text
        assert job.message == "held: arrival is in the recycle bin"
        arrival = await s.get(LiveSet, job.live_set_id)
        assert arrival is not None and arrival.deleted_at is not None
        assert (await s.get(LiveSet, tid)).quality_tier == "ok"


@pytest.mark.parametrize("stage", ["_download", "transcode"])
async def test_failed_upgrade_rip_records_a_rejected_event(
    session, monkeypatch, tmp_path, stage,
):
    """R31: a download/probe/transcode failure on an upgrade attempt writes a
    rejected event for the target, so the next sweep doesn't re-pick the same
    candidate forever."""
    from setvault_core.db import session_factory
    from setvault_core.models.upgrades import SetUpgradeEvent, already_tried
    from sqlalchemy import select

    tid, job_id, _user, _calls = await _upgrade_rip_setup(
        session, monkeypatch, tmp_path, arrival_tier="lossless", matches=True,
    )

    async def _boom(*a, **kw):
        raise RuntimeError("boom at " + stage)

    if stage == "_download":
        monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _boom)
    else:
        monkeypatch.setattr("setvault_core.jobs.transcode.transcode_audio", _boom)

    await _run_rip_job(session, job_id)

    async with session_factory()() as s:
        job = await s.get(RipJob, job_id)
        assert job.status == "failed"
        [event] = (await s.execute(select(SetUpgradeEvent).where(
            SetUpgradeEvent.live_set_id == tid))).scalars().all()
        assert event.outcome == "rejected"
        assert event.reason.startswith("rip failed: ")
        assert "boom at" in event.reason
        assert event.trigger == "scheduled"
        assert (event.candidate_source_kind, event.candidate_external_id) == (
            "bandcamp", "bc-1")
        assert event.to_source_url == "https://x.bandcamp.com/track/t"
        assert await already_tried(s, tid, source_kind="bandcamp", external_id="bc-1")


async def test_failed_plain_rip_records_no_upgrade_event(session, monkeypatch, tmp_path):
    from setvault_core.models.upgrades import SetUpgradeEvent
    from sqlalchemy import func, select

    user = await _make_user(session)
    await _make_root(session, tmp_path)
    job_id = await _queued_rip(session, user)
    before = await session.scalar(select(func.count()).select_from(SetUpgradeEvent))

    async def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("setvault_core.jobs.url_rip_job._download", _boom)
    await _run_rip_job(session, job_id)
    after = await session.scalar(select(func.count()).select_from(SetUpgradeEvent))
    assert after == before

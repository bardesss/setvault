import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from setvault_core.db import engine, init_engine, run_job, session_factory
from setvault_core.jobs.pipeline import run_pipeline
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User


async def _make_set(tmp_path: Path) -> uuid.UUID:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="missing.flac", uploaded_by=u.id, source_type="upload",
                       status="processing")
        s.add(live)
        await s.commit()
        return live.id


async def _status(sid: uuid.UUID) -> str:
    async with session_factory()() as s:
        return (await s.get(LiveSet, sid)).status


def test_failed_pipeline_marks_set_failed(tmp_path: Path, monkeypatch):
    """A failing step must flip the set to ``failed`` instead of leaving it
    stuck in ``processing``. Runs with the worker's real pooled engine: the
    pipeline and the failure handler use separate ``asyncio.run`` loops, and a
    pooled asyncpg connection from the first loop can't be reused in the second.
    """
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    sid = asyncio.run(_make_set(tmp_path))

    monkeypatch.delenv("SETVAULT_DB_NULLPOOL")
    monkeypatch.setenv("DATABASE_URL", url)
    # The source file doesn't exist, so the first step (probe) fails.
    with pytest.raises(Exception):  # noqa: B017
        run_pipeline(str(sid))

    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    assert asyncio.run(_status(sid)) == "failed"


def _spy_engines(monkeypatch) -> list:
    """Record every engine init_engine() builds while an event loop runs."""
    import setvault_core.db as db

    built: list = []
    real = db.create_async_engine

    def _spy(*a, **kw):
        eng = real(*a, **kw)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return eng
        built.append(eng)
        return eng

    monkeypatch.setattr(db, "create_async_engine", _spy)
    return built


def test_failed_pipeline_leaves_no_pooled_connections(tmp_path: Path, monkeypatch):
    """Each sync entrypoint must dispose its pooled engine before its loop
    closes; otherwise the pool keeps asyncpg connections bound to a dead loop.
    Two back-to-back runs model a non-forking worker process."""
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    sids = [asyncio.run(_make_set(tmp_path)) for _ in range(2)]

    monkeypatch.delenv("SETVAULT_DB_NULLPOOL")
    monkeypatch.setenv("DATABASE_URL", url)
    for sid in sids:
        with pytest.raises(Exception):  # noqa: B017
            run_pipeline(str(sid))
        assert engine().sync_engine.pool.checkedin() == 0

    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    assert [asyncio.run(_status(sid)) for sid in sids] == ["failed", "failed"]


def test_pipeline_stages_share_one_engine(tmp_path: Path, monkeypatch, require_tools):
    """Every stage calls init_engine(); within one run they must reuse a single
    pooled engine rather than strand a pool per stage."""
    require_tools("ffmpeg", "fpcalc", "audiowaveform")
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    subprocess.run(  # noqa: S603
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",  # noqa: S607
         str(tmp_path / "missing.flac")],
        check=True, capture_output=True,
    )
    sid = asyncio.run(_make_set(tmp_path))

    monkeypatch.delenv("SETVAULT_DB_NULLPOOL")
    monkeypatch.setenv("DATABASE_URL", url)
    built = _spy_engines(monkeypatch)
    run_pipeline(str(sid))

    assert len(built) == 1
    assert built[0].sync_engine.pool.checkedin() == 0

    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    assert asyncio.run(_status(sid)) == "published"


def test_init_engine_reuses_engine_on_same_loop_only(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.delenv("SETVAULT_DB_NULLPOOL", raising=False)

    async def _twice():
        return init_engine(url), init_engine(url)

    a, b = run_job(_twice())
    c, _ = run_job(_twice())
    assert a is b
    assert c is not a


def test_pipeline_order(tmp_path: Path, monkeypatch):
    """Normalize measures the original before transcode, so transcode can
    apply the gain (P2a A3)."""
    import setvault_core.jobs.fingerprint as fingerprint
    import setvault_core.jobs.normalize as normalize
    import setvault_core.jobs.pipeline as pipeline
    import setvault_core.jobs.ready as ready
    import setvault_core.jobs.transcode as transcode
    import setvault_core.jobs.waveform as waveform

    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    sid = asyncio.run(_make_set(tmp_path))

    calls: list[str] = []

    def _step(name):
        async def _fn(live_set_id, **kwargs):
            calls.append(name)
        return _fn

    monkeypatch.setattr(pipeline, "probe_audio", _step("probe"))
    monkeypatch.setattr(fingerprint, "fingerprint_audio", _step("fingerprint"))
    monkeypatch.setattr(normalize, "normalize_audio", _step("normalize"))
    monkeypatch.setattr(transcode, "transcode_audio", _step("transcode"))
    monkeypatch.setattr(waveform, "generate_waveform", _step("waveform"))
    monkeypatch.setattr(ready, "mark_ready", _step("ready"))

    run_pipeline(str(sid))

    assert calls == ["probe", "fingerprint", "normalize", "transcode", "waveform", "ready"]
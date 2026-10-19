import array
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import quality_backfill as qb
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.identity import User
from setvault_core.services.audio_match import MATCHER_VERSION
from setvault_core.services.audio_quality import AudioQuality
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def _seed(tmp_path: Path, names: list[str]) -> dict[str, uuid.UUID]:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = {}
        for n in names:
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                           audio_path=n, uploaded_by=u.id, source_type="upload",
                           status="published")
            s.add(live)
            await s.flush()
            ids[n] = live.id
        await s.commit()
        return ids


def _tone(path: Path) -> None:
    subprocess.run(  # noqa: S603
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",  # noqa: S607
         str(path)],
        check=True, capture_output=True,
    )


async def test_backfill_fills_missing_fingerprint_and_quality(tmp_path: Path, require_tools):
    require_tools("ffmpeg", "ffprobe", "fpcalc")
    _tone(tmp_path / "a.flac")
    ids = await _seed(tmp_path, ["a.flac"])

    async with session_factory()() as s:
        before = await qb.backfill_candidates(s)
    assert before == {"to_fingerprint": 1, "to_measure": 1, "failed": 0}

    res = await qb.run_backfill_batch()
    assert res["processed"] == 1 and res["errors"] == 0 and res["remaining"] == 0

    async with session_factory()() as s:
        live = await s.get(LiveSet, ids["a.flac"])
        assert live.quality_tier is not None
        assert live.quality_measured_at is not None
        assert live.status == "published"
        assert live.duplicate_of is None
        fps = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == live.id)
        )).scalars().all()
        assert len(fps) == 1
        assert fps[0].raw and fps[0].raw_version == MATCHER_VERSION


async def test_backfill_skips_already_done(tmp_path: Path, monkeypatch):
    ids = await _seed(tmp_path, ["done.flac"])
    async with session_factory()() as s:
        live = await s.get(LiveSet, ids["done.flac"])
        live.quality_measured_at = datetime.now(UTC)
        s.add(SetFingerprint(live_set_id=live.id, fingerprint_hash="h", duration_seconds=1.0,
                             raw=b"\x01\x00\x00\x00", raw_version=MATCHER_VERSION))
        await s.commit()

    def boom(*_a, **_k):
        raise AssertionError("must not recompute")
    monkeypatch.setattr(qb, "compute_raw_fingerprint", boom)
    monkeypatch.setattr(qb, "compute_legacy_digest", boom)
    monkeypatch.setattr(qb, "measure_quality", boom)

    async with session_factory()() as s:
        assert await qb.backfill_candidates(s) == {
            "to_fingerprint": 0, "to_measure": 0, "failed": 0,
        }
    res = await qb.run_backfill_batch()
    assert (res["processed"], res["errors"], res["remaining"]) == (0, 0, 0)


async def test_backfill_continues_after_one_bad_file(tmp_path: Path, monkeypatch):
    (tmp_path / "ok.flac").write_bytes(b"x")
    ids = await _seed(tmp_path, ["gone.flac", "ok.flac"])  # gone.flac has no file
    monkeypatch.setattr(
        qb, "compute_raw_fingerprint",
        lambda _p: (array.array("I", [1, 2, 3]), 3.0),
    )
    monkeypatch.setattr(qb, "compute_legacy_digest", lambda _p: "legacy")
    monkeypatch.setattr(
        qb, "measure_quality",
        lambda _p: AudioQuality("flac", None, 44100, 16, True, "lossless"),
    )

    res = await qb.run_backfill_batch()
    assert res["processed"] == 1 and res["errors"] == 1
    assert res["error_ids"] == [ids["gone.flac"]]

    async with session_factory()() as s:
        ok = await s.get(LiveSet, ids["ok.flac"])
        assert ok.quality_tier == "lossless"
        gone = await s.get(LiveSet, ids["gone.flac"])
        assert gone.quality_measured_at is None

        # The failure is persisted, so the set is not picked up again.
        assert gone.quality_backfill_failed_at is not None
        assert await qb.backfill_candidates(s) == {
            "to_fingerprint": 0, "to_measure": 0, "failed": 1,
        }

    res = await qb.run_backfill_batch()
    assert (res["processed"], res["errors"], res["remaining"]) == (0, 0, 0)


async def test_batch_stops_at_deadline_and_reports_remaining(tmp_path: Path, monkeypatch):
    for n in ("a.flac", "b.flac", "c.flac"):
        (tmp_path / n).write_bytes(b"x")
    await _seed(tmp_path, ["a.flac", "b.flac", "c.flac"])
    monkeypatch.setattr(
        qb, "compute_raw_fingerprint",
        lambda _p: (array.array("I", [1, 2, 3]), 3.0),
    )
    monkeypatch.setattr(qb, "compute_legacy_digest", lambda _p: "legacy")
    monkeypatch.setattr(
        qb, "measure_quality",
        lambda _p: AudioQuality("flac", None, 44100, 16, True, "lossless"),
    )
    # First deadline check passes, every later one is past the deadline.
    ticks = iter([0.0])

    res = await qb.run_backfill_batch(
        deadline=100.0, clock=lambda: next(ticks, 10_000.0),
    )
    assert res["processed"] == 1 and res["errors"] == 0
    assert res["remaining"] == 2



def _stub_tools(monkeypatch):
    monkeypatch.setattr(
        qb, "compute_raw_fingerprint",
        lambda _p: (array.array("I", [1, 2, 3]), 3.0),
    )
    monkeypatch.setattr(qb, "compute_legacy_digest", lambda _p: "legacy")
    monkeypatch.setattr(
        qb, "measure_quality",
        lambda _p: AudioQuality("flac", None, 44100, 16, True, "lossless"),
    )


@pytest.fixture
def fake_queue(monkeypatch):
    import rq

    calls: list[tuple[str, dict]] = []

    class _Job:
        id = "job-next"

    def _enqueue(self, func, **kwargs):
        calls.append((self.name, func, kwargs))
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)
    return calls


async def test_job_runs_one_slice_and_enqueues_the_next(
    tmp_path: Path, monkeypatch, fake_queue,
):
    names = ["a.flac", "b.flac", "c.flac"]
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    await _seed(tmp_path, names)
    _stub_tools(monkeypatch)
    monkeypatch.setattr(qb, "BATCH_MAX_SETS", 2)

    res = await qb._run_quality_backfill()

    assert res["processed"] == 2 and res["remaining"] == 1
    assert fake_queue == [(
        "default", "setvault_core.jobs.quality_backfill.run_quality_backfill",
        {"job_timeout": qb.QUALITY_BACKFILL_TIMEOUT},
    )]


async def test_job_slice_is_time_bounded(tmp_path: Path, monkeypatch, fake_queue):
    names = ["a.flac", "b.flac"]
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    await _seed(tmp_path, names)
    _stub_tools(monkeypatch)
    # Slice start, first per-set check, then past BATCH_SECONDS.
    ticks = iter([0.0, 0.0])

    res = await qb._run_quality_backfill(
        clock=lambda: next(ticks, qb.BATCH_SECONDS + 1.0),
    )

    assert res["processed"] == 1 and res["remaining"] == 1
    assert len(fake_queue) == 1


async def test_job_does_not_enqueue_when_done(tmp_path: Path, monkeypatch, fake_queue):
    (tmp_path / "a.flac").write_bytes(b"x")
    await _seed(tmp_path, ["a.flac"])
    _stub_tools(monkeypatch)

    res = await qb._run_quality_backfill()

    assert res["processed"] == 1 and res["remaining"] == 0
    assert fake_queue == []


async def test_failed_set_is_marked_and_not_retried(tmp_path: Path, monkeypatch, fake_queue):
    ids = await _seed(tmp_path, ["missing.flac"])  # no file on disk
    _stub_tools(monkeypatch)

    res = await qb._run_quality_backfill()
    assert res["errors"] == 1 and res["remaining"] == 0
    assert fake_queue == []

    async with session_factory()() as s:
        live = await s.get(LiveSet, ids["missing.flac"])
        assert live.quality_backfill_failed_at is not None
        assert live.status == "published" and live.deleted_at is None

    res = await qb._run_quality_backfill()
    assert (res["processed"], res["errors"]) == (0, 0)


async def test_cleanup_run_carries_fill_errors_into_summary(
    tmp_path: Path, monkeypatch, fake_queue,
):
    await _seed(tmp_path, ["missing.flac"])  # no file on disk -> fill error
    _stub_tools(monkeypatch)

    res = await qb._run_quality_backfill(cleanup=True, phase="fill")

    assert res["errors"] == 1
    # The cleanup slice is queued with the fill errors in its running counts.
    assert len(fake_queue) == 1
    state = fake_queue[0][2]["kwargs"]
    assert state["phase"] == "cleanup"
    assert state["counts"]["errors"] == 1


async def test_set_hard_deleted_during_fpcalc_is_skipped(tmp_path: Path, monkeypatch):
    """The set vanishes while fpcalc runs (no DB session is held then): the
    write must skip it, not fail with a foreign-key IntegrityError."""
    import asyncio

    from sqlalchemy import delete

    (tmp_path / "a.flac").write_bytes(b"x")
    ids = await _seed(tmp_path, ["a.flac"])
    loop = asyncio.get_running_loop()

    async def _hard_delete():
        async with session_factory()() as s:
            await s.execute(delete(LiveSet).where(LiveSet.id == ids["a.flac"]))
            await s.commit()

    def fpcalc_then_delete(_p):
        asyncio.run_coroutine_threadsafe(_hard_delete(), loop).result()
        return array.array("I", [1, 2, 3]), 3.0

    _stub_tools(monkeypatch)
    monkeypatch.setattr(qb, "compute_raw_fingerprint", fpcalc_then_delete)

    res = await qb.run_backfill_batch()
    assert res["errors"] == 0 and res["error_ids"] == []
    assert res["fingerprinted"] == 0
    async with session_factory()() as s:
        assert (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == ids["a.flac"])
        )).first() is None


async def _mark(live_set_id: uuid.UUID, when: datetime) -> None:
    async with session_factory()() as s:
        (await s.get(LiveSet, live_set_id)).quality_backfill_failed_at = when
        await s.commit()


async def test_clear_backfill_failures_resets_every_marker(tmp_path: Path):
    ids = await _seed(tmp_path, ["a.flac", "b.flac"])
    for sid in ids.values():
        await _mark(sid, datetime.now(UTC))
    async with session_factory()() as s:
        assert (await qb.backfill_candidates(s))["failed"] == 2
        assert await qb.clear_backfill_failures(s) == 2
        await s.commit()
        assert (await qb.backfill_candidates(s))["failed"] == 0
        assert (await qb.backfill_candidates(s))["to_measure"] == 2


async def test_marker_cleared_when_file_changed_after_the_failure(
    tmp_path: Path, monkeypatch,
):
    from datetime import timedelta

    for n in ("fixed.flac", "same.flac"):
        (tmp_path / n).write_bytes(b"x")
    ids = await _seed(tmp_path, ["fixed.flac", "same.flac"])
    now = datetime.now(UTC)
    # fixed.flac was replaced after it failed; same.flac hasn't changed since.
    await _mark(ids["fixed.flac"], now - timedelta(hours=1))
    await _mark(ids["same.flac"], now + timedelta(hours=1))
    _stub_tools(monkeypatch)

    res = await qb.run_backfill_batch()

    assert res["processed"] == 1 and res["errors"] == 0
    async with session_factory()() as s:
        fixed = await s.get(LiveSet, ids["fixed.flac"])
        assert fixed.quality_backfill_failed_at is None
        assert fixed.quality_tier == "lossless"
        same = await s.get(LiveSet, ids["same.flac"])
        assert same.quality_backfill_failed_at is not None
        assert same.quality_measured_at is None


async def test_backfill_chain_is_a_singleton():
    from redis import Redis
    from rq.job import Job

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    redis.delete(qb.CHAIN_KEY)
    first = qb.start_quality_backfill()
    try:
        assert first is not None
        assert qb.quality_backfill_in_flight() is True
        assert qb.start_quality_backfill() is None
        assert qb.start_quality_backfill(cleanup=True) is None
    finally:
        Job.fetch(first.id, connection=redis).delete()
    assert qb.quality_backfill_in_flight() is False
    second = qb.start_quality_backfill()
    try:
        assert second is not None and second.id != first.id
    finally:
        Job.fetch(second.id, connection=redis).delete()
        redis.delete(qb.CHAIN_KEY)


def test_start_while_another_start_holds_the_lock_enqueues_nothing(monkeypatch):
    import rq
    from redis import Redis

    calls = []
    monkeypatch.setattr(rq.Queue, "enqueue", lambda self, func, **kw: calls.append(func))
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    redis.delete(qb.CHAIN_KEY)
    redis.set(qb.START_LOCK_KEY, "1", ex=30)
    try:
        assert qb.start_quality_backfill() is None
        assert qb.start_quality_backfill(cleanup=True) is None
        assert calls == []
        # The other start's lock is not released by the refused one.
        assert redis.get(qb.START_LOCK_KEY) is not None
    finally:
        redis.delete(qb.START_LOCK_KEY)

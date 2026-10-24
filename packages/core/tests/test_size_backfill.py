import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import size_backfill
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


def _write(root: Path, rel: str, size: int) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)


async def _seed(tmp_path: Path, rows: dict[str, dict]) -> dict[str, uuid.UUID]:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = {}
        for name, fields in rows.items():
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title=name, media_root_id=r.id,
                           audio_path=f"originals/{name}.flac", uploaded_by=u.id,
                           source_type="upload", status="published", **fields)
            s.add(live)
            await s.flush()
            ids[name] = live.id
        await s.commit()
    return ids


async def _sizes(set_id: uuid.UUID) -> tuple[int | None, int | None]:
    async with session_factory()() as s:
        live = await s.get(LiveSet, set_id)
        return live.audio_bytes, live.stream_bytes


async def test_size_backfill_fills_and_counts_missing(tmp_path: Path, monkeypatch):
    # Small batches, so the run has to page through the sets.
    monkeypatch.setattr(size_backfill, "BATCH_SIZE", 2)
    ids = await _seed(tmp_path, {
        "both": {"streaming_path": "stream/both.opus"},
        "no_stream": {},
        "audio_gone": {"streaming_path": "stream/audio_gone.opus"},
        "known_audio": {"streaming_path": "stream/known_audio.opus", "audio_bytes": 42},
        "recycled": {"streaming_path": "stream/recycled.opus",
                     "deleted_at": datetime.now(UTC)},
        "done": {"streaming_path": "stream/done.opus", "audio_bytes": 1, "stream_bytes": 2},
    })
    _write(tmp_path, "originals/both.flac", 500)
    _write(tmp_path, "stream/both.opus", 50)
    _write(tmp_path, "originals/no_stream.flac", 300)
    _write(tmp_path, "stream/audio_gone.opus", 30)  # its audio file is missing
    _write(tmp_path, "originals/known_audio.flac", 5)
    _write(tmp_path, "stream/known_audio.opus", 7)
    _write(tmp_path, "originals/recycled.flac", 11)
    _write(tmp_path, "stream/recycled.opus", 12)
    _write(tmp_path, "originals/done.flac", 99)
    _write(tmp_path, "stream/done.opus", 99)

    res = await size_backfill._run_size_backfill()

    # Four sets lack a size; five files were found and measured, one is gone.
    assert res == {"checked": 4, "filled": 5, "missing": 1}
    assert await _sizes(ids["both"]) == (500, 50)
    assert await _sizes(ids["no_stream"]) == (300, None)
    assert await _sizes(ids["audio_gone"]) == (None, 30)
    assert await _sizes(ids["known_audio"]) == (42, 7)  # a known size is kept
    assert await _sizes(ids["recycled"]) == (None, None)
    assert await _sizes(ids["done"]) == (1, 2)

    # A second run finds only the set whose audio is still missing.
    assert await size_backfill._run_size_backfill() == {"checked": 1, "filled": 0, "missing": 1}


async def test_enqueue_if_needed_only_when_nulls(tmp_path: Path, monkeypatch):
    queued: list[bool] = []
    def fake_enqueue(redis=None) -> bool:
        queued.append(True)
        return True

    monkeypatch.setattr(size_backfill, "_enqueue", fake_enqueue)

    async def check() -> bool:
        async with session_factory()() as s:
            return await size_backfill.enqueue_if_needed(s)

    assert await check() is False  # no sets at all

    ids = await _seed(tmp_path, {
        # Sized audio and no stream: nothing to fill.
        "no_stream": {"audio_bytes": 10},
        # Recycled sets are left alone.
        "recycled": {"streaming_path": "stream/r.opus", "deleted_at": datetime.now(UTC)},
        "sized": {"streaming_path": "stream/s.opus", "audio_bytes": 1, "stream_bytes": 2},
    })
    assert await check() is False
    assert queued == []

    async with session_factory()() as s:
        (await s.get(LiveSet, ids["sized"])).stream_bytes = None
        await s.commit()
    assert await check() is True
    assert queued == [True]

    async with session_factory()() as s:
        live = await s.get(LiveSet, ids["sized"])
        live.stream_bytes, live.audio_bytes = 2, None
        await s.commit()
    assert await check() is True
    assert queued == [True, True]


@pytest.fixture
def backfill_queue(monkeypatch):
    """A private queue name and job id on the test Redis, removed afterwards."""
    from rq import Queue
    from rq.job import Job

    tag = uuid.uuid4().hex[:8]
    monkeypatch.setattr(size_backfill, "SIZE_BACKFILL_QUEUE", f"test-size-{tag}")
    monkeypatch.setattr(size_backfill, "JOB_ID", f"test-size-backfill-{tag}")
    redis = size_backfill._redis()
    yield redis
    queue = Queue(size_backfill.SIZE_BACKFILL_QUEUE, connection=redis)
    job = Job.fetch_many([size_backfill.JOB_ID], connection=redis)[0]
    if job is not None:
        job.delete()
    queue.delete(delete_jobs=True)


def test_enqueue_queues_once_on_low_with_timeout(backfill_queue):
    from rq import Queue
    from rq.job import Job

    redis = backfill_queue
    assert size_backfill._enqueue(redis) is True
    job = Job.fetch(size_backfill.JOB_ID, connection=redis)
    assert job.func_name == "setvault_core.jobs.size_backfill.run_size_backfill"
    assert job.timeout == 3600
    assert job.origin == size_backfill.SIZE_BACKFILL_QUEUE

    # Still queued (a worker restart before it ran): not queued again.
    assert size_backfill._enqueue(redis) is False
    queue = Queue(size_backfill.SIZE_BACKFILL_QUEUE, connection=redis)
    assert queue.job_ids == [size_backfill.JOB_ID]

    # Once it has finished, a later start may queue it again.
    job.set_status("finished")
    queue.remove(job)
    assert size_backfill._enqueue(redis) is True
    assert queue.job_ids == [size_backfill.JOB_ID]


def test_default_redis_has_timeouts():
    kwargs = size_backfill._redis().connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == size_backfill.REDIS_TIMEOUT_SECONDS
    assert kwargs["socket_timeout"] == size_backfill.REDIS_TIMEOUT_SECONDS

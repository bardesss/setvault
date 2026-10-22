"""Every enqueue of a long-running ingest job must override RQ's 180s default
job timeout; otherwise any real-length set is killed mid-pipeline."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import ClassVar

import pytest
import rq
from setvault_core.jobs.pipeline import PIPELINE_JOB_TIMEOUT
from setvault_core.jobs.url_rip_job import RIP_JOB_TIMEOUT


class _FakeQueue:
    calls: ClassVar[list[tuple[tuple, dict]]] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def enqueue(self, *args, **kwargs):
        _FakeQueue.calls.append((args, kwargs))


@pytest.fixture
def fake_queue(monkeypatch):
    _FakeQueue.calls = []
    monkeypatch.setattr(rq, "Queue", _FakeQueue)
    return _FakeQueue.calls


async def test_watch_folder_pipeline_enqueue_sets_timeout(fake_queue):
    from setvault_core.jobs.watch_folder_ingest import _trigger_pipeline

    await _trigger_pipeline(uuid.uuid4())

    (args, kwargs), = fake_queue
    assert args[0] == "setvault_core.jobs.pipeline.run_pipeline"
    assert kwargs["job_timeout"] == PIPELINE_JOB_TIMEOUT


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self):
        self.commits += 1


async def test_enqueue_rip_sets_timeout_and_returns_true(fake_queue):
    from setvault_core.services.rip_enqueue import enqueue_rip

    session = _Session()
    job = SimpleNamespace(id=uuid.uuid4(), status="queued", error_text=None)
    assert await enqueue_rip(session, job) is True

    (args, kwargs), = fake_queue
    assert args[0] == "setvault_core.jobs.url_rip_job.run_rip_job"
    assert kwargs["job_timeout"] == RIP_JOB_TIMEOUT
    assert kwargs["rip_job_id"] == str(job.id)
    assert session.commits == 1


async def test_enqueue_rip_marks_job_failed_when_enqueue_raises(monkeypatch):
    from setvault_core.services.rip_enqueue import enqueue_rip

    class _Down(_FakeQueue):
        def enqueue(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(rq, "Queue", _Down)
    session = _Session()
    job = SimpleNamespace(id=uuid.uuid4(), status="queued", error_text=None)
    assert await enqueue_rip(session, job) is False
    assert job.status == "failed" and job.error_text == "failed to enqueue worker"
    assert session.commits == 2

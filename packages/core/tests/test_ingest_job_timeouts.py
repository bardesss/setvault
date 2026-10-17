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
from setvault_ingest_sources.base import Candidate


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


async def test_monitor_auto_ingest_enqueue_sets_timeout(fake_queue, monkeypatch):
    from setvault_core.services import discoveries, url_rip

    job_id = uuid.uuid4()

    async def _fake_submit(_session, *, user_id, url):
        return SimpleNamespace(id=job_id)

    monkeypatch.setattr(url_rip, "submit_rip", _fake_submit)
    candidate = Candidate(
        source_kind="youtube", external_id="x", title="t", uploader=None,
        duration_seconds=None, thumbnail_url=None,
        webpage_url="https://www.youtube.com/watch?v=x",
    )
    monitor = SimpleNamespace(id=uuid.uuid4(), owner_user_id=uuid.uuid4())

    assert await discoveries._ingest_candidate(
        None, monitor=monitor, candidate=candidate,
    ) == job_id

    (args, kwargs), = fake_queue
    assert args[0] == "setvault_core.jobs.url_rip_job.run_rip_job"
    assert kwargs["job_timeout"] == RIP_JOB_TIMEOUT

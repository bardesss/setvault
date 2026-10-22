"""RecordingWorker writes one ``jobs`` row per RQ run (spec §4.5 #8).

The hooks are called directly with a fake rq Job (the parent rq.Worker hooks
are stubbed, so no Redis bookkeeping happens); one end-to-end test drives a
real ``perform_job`` against Redis to prove the overrides match RQ's calls.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import rq
from redis import Redis
from setvault_core.models.identity import User
from setvault_core.models.system import Job
from sqlalchemy import insert, select

RQ_PREFIX = "wtest-"
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Separate DB from test_scheduler_wiring's (9): the e2e test flushes it.
_E2E_REDIS_URL = os.environ.get("TEST_WORKER_REDIS_URL", "redis://localhost:6379/10")
_UNREACHABLE_DB = "postgresql+asyncpg://setvault:setvault@127.0.0.1:1/setvault"

_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "x.py", line 1, in <module>\n'
    "    raise ValueError('boom')\n"
    "ValueError: boom\n"
)


class FakeJob:
    """The slice of ``rq.job.Job`` the recording hooks touch."""

    def __init__(self, rq_id: str, func_name: str, kwargs: dict | None = None):
        self.id = rq_id
        self.func_name = func_name
        self.kwargs = kwargs or {}
        self.meta: dict = {}
        self.saved_meta: list[dict] = []
        self.started_at = None
        self._result = None

    def save_meta(self) -> None:
        self.saved_meta.append(dict(self.meta))

    def get_meta(self, refresh: bool = True) -> dict:
        return self.meta


@pytest.fixture
def parent_calls(monkeypatch):
    """Stub rq.Worker's own hooks and record that they were still called."""
    calls: list[str] = []
    monkeypatch.setattr(rq.Worker, "prepare_job_execution",
                        lambda self, job, *a, **k: calls.append("prepare"))
    monkeypatch.setattr(rq.Worker, "handle_job_success",
                        lambda self, job, queue, started_job_registry: calls.append("success"))
    monkeypatch.setattr(rq.Worker, "handle_job_failure",
                        lambda self, job, queue, started_job_registry=None, exc_string="":
                        calls.append("failure"))
    return calls


def _worker(database_url: str):
    from setvault_worker.recording import RecordingWorker

    return RecordingWorker(["default"], connection=Redis.from_url(_REDIS_URL),
                           database_url=database_url)


@pytest.fixture
def worker(db_url, parent_calls):
    return _worker(db_url)


def _rows(run_db, rq_id: str) -> list[Job]:
    async def _q(conn):
        return (await conn.execute(
            select(Job.__table__).where(Job.rq_id == rq_id).order_by(Job.created_at)
        )).all()
    return run_db(_q)


def _succeed(worker, job, result=None):
    worker.prepare_job_execution(job)
    job._result = result
    worker.handle_job_success(job, None, None)


def _fail(worker, job, exc_string=_TRACEBACK):
    worker.prepare_job_execution(job)
    worker.handle_job_failure(job, None, None, exc_string=exc_string)


# --- pure helpers -----------------------------------------------------------

def test_short_kind_is_last_two_dotted_parts():
    from setvault_worker.recording import short_kind

    assert short_kind("setvault_core.jobs.email.send_email_job") == "email.send_email_job"
    assert short_kind("email.send_email_job") == "email.send_email_job"
    assert short_kind("send_email_job") == "send_email_job"


def test_quiet_kinds_map_to_the_real_job_paths():
    """QUIET_KINDS = media-root health checks, monitor dispatch, monitor polls
    and tus-spool prune, spelled as the short kinds of their real func paths."""
    from setvault_worker.entrypoint import _SCHEDULE
    from setvault_worker.recording import QUIET_KINDS, short_kind

    scheduled = {entry[0] for entry in _SCHEDULE}
    quiet_paths = {
        "setvault_core.jobs.media_root_health.run_health_checks_sync",
        "setvault_core.jobs.monitor_dispatch.run_dispatch_monitors",
        "setvault_core.jobs.tus_spool_prune.run_prune_tus_spool",
    }
    assert quiet_paths <= scheduled
    # monitor polls are enqueued by the dispatch job, not scheduled
    import inspect

    import setvault_core.jobs.monitor_dispatch as dispatch
    poll_path = "setvault_core.jobs.monitor_poll.run_poll_monitor"
    assert poll_path in inspect.getsource(dispatch)
    quiet_paths.add(poll_path)

    assert {short_kind(p) for p in quiet_paths} == QUIET_KINDS
    # every other scheduled job is recorded per run
    for path in scheduled - quiet_paths:
        assert short_kind(path) not in QUIET_KINDS


def test_redact_matches_whole_key_words_only():
    from setvault_worker.recording import REDACTED, redact

    out = redact({
        "to": "a@b", "set_id": "x", "total": 3, "email": "a@b",
        "recipient_email": "a@b", "reset_link": "https://x", "webhook_url": "u",
        "access_token": "t", "password": "p", "client_secret": "s",
        "ip_address": "1.2.3.4", "callbackUrl": "u", "emails": ["a@b"],
        "addresses": ["a"], "tokenize": False, "history": "h", "stop": 1,
        "nested": {"to": "a@b", "count": 2}, "items": [{"url": "u", "id": 1}],
        "photo": "p",
    })
    assert out == {
        "to": REDACTED, "set_id": "x", "total": 3, "email": REDACTED,
        "recipient_email": REDACTED, "reset_link": REDACTED, "webhook_url": REDACTED,
        "access_token": REDACTED, "password": REDACTED, "client_secret": REDACTED,
        "ip_address": REDACTED, "callbackUrl": REDACTED, "emails": REDACTED,
        "addresses": REDACTED, "tokenize": False, "history": "h", "stop": 1,
        "nested": {"to": REDACTED, "count": 2}, "items": [{"url": REDACTED, "id": 1}],
        "photo": "p",
    }
    assert redact({"TO": "a@b", "Email": "a@b"}) == {"TO": REDACTED, "Email": REDACTED}


def test_redact_makes_values_json_safe():
    from setvault_worker.recording import redact

    uid = uuid.uuid4()
    assert redact({"set_id": uid, "ids": (1, 2)}) == {"set_id": str(uid), "ids": [1, 2]}


# --- hooks ------------------------------------------------------------------

def test_two_runs_same_rq_id_make_two_rows(worker, run_db, parent_calls):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    for n in range(2):
        job = FakeJob(rq_id, "setvault_core.jobs.recycle_bin_purge.run_purge_recycle_bin")
        _succeed(worker, job, result={"purged": n})
        assert job.saved_meta and job.saved_meta[-1]["setvault_job_row"]

    rows = _rows(run_db, rq_id)
    assert len(rows) == 2
    assert rows[0].id != rows[1].id
    assert {r.kind for r in rows} == {"recycle_bin_purge.run_purge_recycle_bin"}
    assert [r.status for r in rows] == ["finished", "finished"]
    assert [r.result for r in rows] == [{"purged": 0}, {"purged": 1}]
    assert all(r.started_at and r.finished_at and r.finished_at >= r.started_at
               for r in rows)
    assert parent_calls == ["prepare", "success", "prepare", "success"]


def test_started_row_is_visible_while_running(worker, run_db):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    job = FakeJob(rq_id, "setvault_core.jobs.bulk_action.run_bulk_action")
    worker.prepare_job_execution(job)
    (row,) = _rows(run_db, rq_id)
    assert row.status == "started"
    assert row.id == job.meta["setvault_job_row"]
    assert row.finished_at is None


def test_non_dict_result_is_not_stored(worker, run_db):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    _succeed(worker, FakeJob(rq_id, "setvault_core.jobs.email.send_email_job"), result=7)
    (row,) = _rows(run_db, rq_id)
    assert row.result == {}


def test_failure_records_message_last_line(worker, run_db, parent_calls):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    _fail(worker, FakeJob(rq_id, "setvault_core.jobs.pipeline.run_pipeline"))
    (row,) = _rows(run_db, rq_id)
    assert row.status == "failed"
    assert row.message == "ValueError: boom"
    assert row.finished_at is not None
    assert parent_calls == ["prepare", "failure"]


def test_failure_without_started_row_still_records(worker, run_db):
    """A work-horse crash is handled by the main worker process, whose copy of
    the job may not carry the row id: the failure is still recorded."""
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    job = FakeJob(rq_id, "setvault_core.jobs.pipeline.run_pipeline")
    worker.handle_job_failure(job, None, None, exc_string="JobTimeoutException: 180s\n")
    (row,) = _rows(run_db, rq_id)
    assert (row.status, row.message) == ("failed", "JobTimeoutException: 180s")


def test_quiet_kind_success_writes_no_row(worker, run_db, parent_calls):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    job = FakeJob(rq_id, "setvault_core.jobs.tus_spool_prune.run_prune_tus_spool")
    _succeed(worker, job, result={"deleted": 0})
    assert _rows(run_db, rq_id) == []
    assert "setvault_job_row" not in job.meta
    assert parent_calls == ["prepare", "success"]


def test_quiet_kind_failure_writes_one_row(worker, run_db):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    job = FakeJob(rq_id, "setvault_core.jobs.monitor_poll.run_poll_monitor",
                  {"monitor_id": "m"})
    _fail(worker, job)
    (row,) = _rows(run_db, rq_id)
    assert row.kind == "monitor_poll.run_poll_monitor"
    assert row.status == "failed"
    assert row.message == "ValueError: boom"
    assert row.payload == {"monitor_id": "m"}
    assert row.started_at is not None and row.finished_at is not None


def test_payload_redacted(worker, run_db):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    _succeed(worker, FakeJob(rq_id, "setvault_core.jobs.email.send_email_job",
                             {"to": "a@b", "set_id": "x"}))
    (row,) = _rows(run_db, rq_id)
    assert row.payload == {"to": "[redacted]", "set_id": "x"}


def test_initiated_by_only_for_existing_user(worker, run_db):
    async def _mk_user(conn):
        uid = uuid.uuid4()
        await conn.execute(insert(User).values(
            id=uid, email=f"{uid.hex[:8]}@wtest.test", username=f"w{uid.hex[:8]}",
            display_name="w", role="user", session_version=0,
        ))
        return uid
    user_id = run_db(_mk_user)

    cases = {
        "known-actor": ({"actor_user_id": str(user_id)}, user_id),
        "known-user": ({"user_id": str(user_id)}, user_id),
        "unknown": ({"actor_user_id": str(uuid.uuid4())}, None),
        "not-uuid": ({"user_id": "nope"}, None),
        "none": ({}, None),
    }
    for name, (kwargs, expected) in cases.items():
        rq_id = f"{RQ_PREFIX}{name}-{uuid.uuid4().hex[:6]}"
        _succeed(worker, FakeJob(rq_id, "setvault_core.jobs.bulk_action.run_bulk_action",
                                 kwargs))
        (row,) = _rows(run_db, rq_id)
        assert row.initiated_by == expected, name


def test_recording_error_never_fails_job(parent_calls):
    """DB unreachable: every hook swallows the error, still runs RQ's own
    handling, and gives up quickly."""
    worker = _worker(_UNREACHABLE_DB)
    t0 = time.monotonic()
    _succeed(worker, FakeJob(f"{RQ_PREFIX}down", "setvault_core.jobs.email.send_email_job"))
    _fail(worker, FakeJob(f"{RQ_PREFIX}down2", "setvault_core.jobs.pipeline.run_pipeline"))
    _fail(worker, FakeJob(f"{RQ_PREFIX}down3",
                          "setvault_core.jobs.tus_spool_prune.run_prune_tus_spool"))
    assert time.monotonic() - t0 < 30
    assert parent_calls == ["prepare", "success", "prepare", "failure", "prepare", "failure"]


def test_save_meta_error_never_fails_job(worker, run_db, parent_calls):
    rq_id = f"{RQ_PREFIX}{uuid.uuid4().hex[:8]}"
    job = FakeJob(rq_id, "setvault_core.jobs.email.send_email_job")

    def _boom():
        raise ConnectionError("redis down")
    job.save_meta = _boom
    _succeed(worker, job)
    assert parent_calls == ["prepare", "success"]


# --- real RQ round trip -----------------------------------------------------

@pytest.fixture
def e2e_redis():
    r = Redis.from_url(_E2E_REDIS_URL)
    r.flushdb()
    yield r
    r.flushdb()


def _perform(worker, queue, job):
    from rq.timeouts import TimerDeathPenalty

    worker.death_penalty_class = TimerDeathPenalty  # SIGALRM-free (works on Windows)
    return worker.perform_job(job, queue)


def test_real_perform_job_records_success_and_failure(db_url, run_db, e2e_redis):
    from setvault_worker.recording import RecordingWorker

    queue = rq.Queue("default", connection=e2e_redis)
    worker = RecordingWorker([queue], connection=e2e_redis, database_url=db_url)

    ok = queue.enqueue("builtins.dict", set_id="x", to="a@b", job_id=f"{RQ_PREFIX}e2e-ok")
    assert _perform(worker, queue, ok) is True
    assert ok.get_status(refresh=True) == "finished"
    (row,) = _rows(run_db, ok.id)
    assert row.status == "finished"
    assert row.kind == "builtins.dict"
    assert row.payload == {"set_id": "x", "to": "[redacted]"}
    assert ok.get_meta(refresh=True)["setvault_job_row"] == row.id

    bad = queue.enqueue("json.loads", s="not json", job_id=f"{RQ_PREFIX}e2e-bad")
    assert _perform(worker, queue, bad) is False
    (row,) = _rows(run_db, bad.id)
    assert row.status == "failed"
    assert row.message.startswith("json.decoder.JSONDecodeError: Expecting value")


def test_real_perform_job_succeeds_with_db_down(e2e_redis):
    from setvault_worker.recording import RecordingWorker

    queue = rq.Queue("default", connection=e2e_redis)
    worker = RecordingWorker([queue], connection=e2e_redis, database_url=_UNREACHABLE_DB)
    job = queue.enqueue("builtins.dict", set_id="x", job_id=f"{RQ_PREFIX}e2e-down")
    assert _perform(worker, queue, job) is True
    assert job.get_status(refresh=True) == "finished"
    assert job.return_value(refresh=True) == {"set_id": "x"}


# --- entrypoint -------------------------------------------------------------

def test_entrypoint_runs_recording_worker(monkeypatch):
    import setvault_worker.entrypoint as ep

    started: list[tuple] = []

    class _FakeWorker:
        def __init__(self, queues, connection, **kwargs):
            started.append(([q.name for q in queues], kwargs))

        def work(self, **kwargs):
            started.append(kwargs)

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", _REDIS_URL)
    monkeypatch.setattr(ep, "init_engine", lambda url: None)
    monkeypatch.setattr(ep, "_bootstrap_scheduler", lambda redis: None)
    monkeypatch.setattr(ep, "RecordingWorker", _FakeWorker)
    ep.main()
    assert started == [
        (["default", "low"], {"database_url": "postgresql+asyncpg://u:p@h/db"}),
        {"with_scheduler": True},
    ]

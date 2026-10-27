import asyncio
import json
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs import webhook_dispatch as wd
from setvault_core.models.library_webhook import LibraryWebhook, WebhookDelivery
from setvault_core.services import webhook_security as ws
from setvault_core.services.crypto import Crypter
from sqlalchemy import delete, func, select

KEY = "k" * 32
SECRET = "whsec-test"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", KEY)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])


@pytest.fixture
def http(monkeypatch):
    """Route dispatch's httpx.AsyncClient through a MockTransport; the handler
    and the captured requests are exposed on the returned object."""
    h = SimpleNamespace(requests=[], status=200, exc=None, before=None)
    real = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        h.requests.append(request)
        if h.before is not None:
            await h.before()
        if h.exc is not None:
            raise h.exc
        return httpx.Response(h.status)

    monkeypatch.setattr(
        wd.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    return h


@pytest.fixture
async def make_webhook():
    init_engine(os.environ["TEST_DATABASE_URL"])
    ids: list[uuid.UUID] = []

    async def _make(*, secret=None, headers=None, enabled=True, body_template=None):
        row = LibraryWebhook(
            name=f"w{uuid.uuid4().hex[:6]}", target_url="https://hook.test/in",
            events=["set.published"], enabled=enabled, body_template=body_template,
        )
        if secret:
            ws.set_secret(row, secret, Crypter(KEY))
        if headers:
            ws.set_headers(row, headers, Crypter(KEY))
        async with session_factory()() as s:
            s.add(row)
            await s.commit()
        ids.append(row.id)
        return str(row.id)

    yield _make
    async with session_factory()() as s:
        await s.execute(delete(LibraryWebhook).where(LibraryWebhook.id.in_(ids)))
        await s.commit()


async def _go(webhook_id, **kw):
    args = dict(webhook_id=webhook_id, event="set.published",
                delivery_id=str(uuid.uuid4()), set_slug="a-set",
                set_id="11111111-1111-1111-1111-111111111111", title="A Set")
    args.update(kw)
    return await wd.dispatch_webhook(**args)


async def _deliveries(webhook_id):
    async with session_factory()() as s:
        return (await s.execute(
            select(WebhookDelivery).where(WebhookDelivery.webhook_id == uuid.UUID(webhook_id))
            .order_by(WebhookDelivery.created_at)
        )).scalars().all()


async def test_signature_matches_sent_bytes(http, make_webhook):
    wid = await make_webhook(secret=SECRET, body_template={"t": "{{title}}", "é": [1, "{{slug}}"]})
    await _go(wid)
    req = http.requests[0]
    expected = {"t": "A Set", "é": [1, "a-set"]}
    assert req.content == json.dumps(expected, separators=(",", ":")).encode()
    assert req.headers["X-SetVault-Signature"] == ws.sign(
        SECRET, int(req.headers["X-SetVault-Timestamp"]), req.content)
    assert req.headers["Content-Type"] == "application/json"
    assert req.headers["X-SetVault-Event"] == "set.published"


async def test_default_body_is_compact_json(http, make_webhook):
    wid = await make_webhook(secret=SECRET)
    await _go(wid)
    assert http.requests[0].content == (
        b'{"event":"set.published","set_slug":"a-set",'
        b'"set_id":"11111111-1111-1111-1111-111111111111","title":"A Set"}'
    )


async def test_unsigned_without_secret(http, make_webhook):
    wid = await make_webhook()
    delivery_id = str(uuid.uuid4())
    await _go(wid, delivery_id=delivery_id)
    h = http.requests[0].headers
    assert "X-SetVault-Signature" not in h
    assert h["X-SetVault-Event"] == "set.published"
    assert h["X-SetVault-Delivery"] == delivery_id
    assert h["X-SetVault-Timestamp"].isdigit()


async def test_custom_headers_decrypted_and_sent(http, make_webhook):
    wid = await make_webhook(headers={"X-Plex-Token": "tok-123"})
    await _go(wid)
    assert http.requests[0].headers["X-Plex-Token"] == "tok-123"


async def test_legacy_plaintext_headers_still_sent(http, make_webhook):
    wid = await make_webhook()
    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(wid))
        row.headers = {"X-Legacy": "yes"}
        await s.commit()
    await _go(wid)
    assert http.requests[0].headers["X-Legacy"] == "yes"


@pytest.mark.parametrize(("status", "error", "expected"), [
    (None, "timeout", True),
    (500, None, True),
    (503, None, True),
    (408, None, True),
    (429, None, True),
    (400, None, False),
    (404, None, False),
    (200, None, False),
])
def test_is_retryable_table(status, error, expected):
    assert wd.is_retryable(status, error) is expected


async def test_retryable_failure_raises_after_logging(http, make_webhook):
    http.status = 503
    wid = await make_webhook()
    with pytest.raises(wd.RetryableDeliveryError):
        await _go(wid)
    rows = await _deliveries(wid)
    assert [(r.attempt, r.status_code) for r in rows] == [(1, 503)]


async def test_network_error_is_retryable_and_logged(http, make_webhook):
    http.exc = httpx.ConnectTimeout("")
    wid = await make_webhook()
    with pytest.raises(wd.RetryableDeliveryError):
        await _go(wid, attempt=3)
    (row,) = await _deliveries(wid)
    assert (row.attempt, row.status_code, row.error) == (3, None, "ConnectTimeout")


async def test_permanent_failure_does_not_raise(http, make_webhook):
    http.status = 404
    wid = await make_webhook()
    result = await _go(wid)
    assert result["status_code"] == 404
    rows = await _deliveries(wid)
    assert [(r.attempt, r.status_code) for r in rows] == [(1, 404)]


async def test_success_updates_last_columns_and_logs(http, make_webhook):
    wid = await make_webhook()
    await _go(wid)
    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(wid))
        assert (row.last_status_code, row.last_error) == (200, None)
        assert row.last_call_at is not None
    (d,) = await _deliveries(wid)
    assert d.error is None
    assert d.duration_ms is not None


async def test_retry_stops_when_webhook_disabled(http, make_webhook):
    wid = await make_webhook(enabled=False)
    result = await _go(wid, attempt=2)
    assert result["skipped"] is True
    assert http.requests == []
    assert await _deliveries(wid) == []


async def test_retry_stops_when_webhook_deleted(http, make_webhook):
    result = await _go(str(uuid.uuid4()))
    assert result["skipped"] is True
    assert http.requests == []


async def test_deleted_during_request_is_skipped(http, make_webhook):
    wid = await make_webhook()

    async def delete_webhook():
        async with session_factory()() as s:
            await s.execute(delete(LibraryWebhook).where(LibraryWebhook.id == uuid.UUID(wid)))
            await s.commit()

    http.before = delete_webhook
    result = await _go(wid)
    assert result["skipped"] is True


async def test_deliveries_pruned_to_50(http, make_webhook):
    wid = await make_webhook()
    for i in range(1, 56):
        await _go(wid, attempt=i)
    rows = await _deliveries(wid)
    assert len(rows) == 50
    assert sorted(r.attempt for r in rows) == list(range(6, 56))


async def test_prune_is_per_webhook(http, make_webhook):
    a, b = await make_webhook(), await make_webhook()
    for _ in range(3):
        await _go(a)
    await _go(b)
    async with session_factory()() as s:
        n = (await s.execute(select(func.count()).select_from(WebhookDelivery)
                             .where(WebhookDelivery.webhook_id == uuid.UUID(b)))).scalar_one()
    assert n == 1


class FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func, **kwargs):
        self.calls.append((func, kwargs))


def test_enqueue_dispatch_sets_retry():
    q = FakeQueue()
    delivery_id = wd.enqueue_dispatch(
        q, webhook_id="w1", event="set.published", set_slug="s", set_id="i", title="t")
    func, kw = q.calls[0]
    assert func == "setvault_core.jobs.webhook_dispatch.run_dispatch_webhook"
    assert kw["delivery_id"] == delivery_id
    assert kw["retry"].max == 5
    assert kw["retry"].intervals == [60, 300, 1800, 7200, 21600]
    assert uuid.UUID(delivery_id).version == 4


def test_enqueue_dispatch_without_retry():
    q = FakeQueue()
    wd.enqueue_dispatch(
        q, webhook_id="w1", event="webhook.test", set_slug=None, set_id=None,
        title=None, retry=False)
    assert "retry" not in q.calls[0][1]


def test_run_dispatch_attempt_comes_from_job_retries_left(monkeypatch):
    seen = []

    async def fake(**kw):
        seen.append(kw["attempt"])
        return {}

    monkeypatch.setattr(wd, "dispatch_webhook", fake)
    monkeypatch.setattr(wd, "run_job", asyncio.run)
    for job, want in [(None, 1), (type("J", (), {"retries_left": 5})(), 1),
                      (type("J", (), {"retries_left": 2})(), 4),
                      (type("J", (), {"retries_left": 0})(), 6),
                      (type("J", (), {"retries_left": None})(), 1)]:
        monkeypatch.setattr(wd, "get_current_job", lambda j=job: j)
        wd.run_dispatch_webhook(webhook_id="x", event="e", delivery_id="d")
        assert seen[-1] == want


async def test_fan_out_webhook_event_enqueues_matching_only(monkeypatch, make_webhook):
    from setvault_core.jobs import ready

    match = await make_webhook()
    q = FakeQueue()
    monkeypatch.setattr("rq.Queue", lambda *a, **k: q)
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **k: object())
    await ready.fan_out_webhook_event(
        "set.published", set_slug="s", set_id="i", title="t")
    await ready.fan_out_webhook_event(
        "set.deleted", set_slug="s", set_id="i", title="t")
    mine = [kw for _, kw in q.calls if kw["webhook_id"] == match]
    assert [kw["event"] for kw in mine] == ["set.published"]


async def test_invalid_url_is_permanent_and_logged(make_webhook, monkeypatch):
    wid = await make_webhook()
    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(wid))
        row.target_url = "not-a-url"
        await s.commit()
    result = await _go(wid)
    assert result["status_code"] is None
    (d,) = await _deliveries(wid)
    assert d.status_code is None
    assert d.error
    async with session_factory()() as s:
        assert (await s.get(LibraryWebhook, uuid.UUID(wid))).last_error == d.error


def test_real_rq_retry_round_trip(http, monkeypatch):
    """Real Redis + RQ: a 503 reschedules the job on the 60s then 300s
    intervals, keeps one delivery id, and a disabled webhook ends the chain."""
    import time

    from redis import Redis
    from rq import Queue, SimpleWorker
    from rq.registry import ScheduledJobRegistry
    from rq.timeouts import TimerDeathPenalty

    http.status = 503
    r = Redis.from_url(os.environ.get("TEST_WEBHOOK_REDIS_URL", "redis://localhost:6379/11"))
    r.flushdb()
    q = Queue("default", connection=r)
    worker = SimpleWorker([q], connection=r)
    worker.death_penalty_class = TimerDeathPenalty  # SIGALRM-free (Windows)
    registry = ScheduledJobRegistry(queue=q)

    def _rows(wid):
        return run_job(_deliveries(wid))

    async def _setup():
        init_engine(os.environ["TEST_DATABASE_URL"])
        row = LibraryWebhook(
            name=f"w{uuid.uuid4().hex[:6]}", target_url="https://hook.test/in",
            events=["set.published"], enabled=True)
        async with session_factory()() as s:
            s.add(row)
            await s.commit()
        return str(row.id)

    async def _disable(wid):
        async with session_factory()() as s:
            (await s.get(LibraryWebhook, uuid.UUID(wid))).enabled = False
            await s.commit()

    async def _cleanup(wid):
        async with session_factory()() as s:
            await s.execute(delete(LibraryWebhook).where(LibraryWebhook.id == uuid.UUID(wid)))
            await s.commit()

    wid = run_job(_setup())
    try:
        did = wd.enqueue_dispatch(
            q, webhook_id=wid, event="set.published", set_slug="s", set_id="i", title="t")
        job = q.jobs[0]

        worker.perform_job(job, q)
        job.refresh()
        assert job.get_status() == "scheduled"
        assert job.retries_left == 4
        assert job.id in registry.get_job_ids()
        assert abs(registry.get_scheduled_time(job).timestamp() - (time.time() + 60)) < 15
        rows = _rows(wid)
        assert [(d.attempt, d.status_code, d.delivery_id) for d in rows] == [(1, 503, did)]

        registry.remove(job)
        worker.perform_job(job, q)
        job.refresh()
        assert job.retries_left == 3
        assert abs(registry.get_scheduled_time(job).timestamp() - (time.time() + 300)) < 15
        rows = _rows(wid)
        assert [(d.attempt, d.delivery_id) for d in rows] == [(1, did), (2, did)]
        assert {q_.headers["X-SetVault-Delivery"] for q_ in http.requests} == {did}

        registry.remove(job)
        run_job(_disable(wid))
        worker.perform_job(job, q)
        job.refresh()
        assert job.get_status() == "finished"
        assert job.return_value()["skipped"] is True
        assert job.id not in registry.get_job_ids()
        assert len(_rows(wid)) == 2
    finally:
        run_job(_cleanup(wid))
        r.flushdb()


async def test_stored_lowercase_reserved_header_cannot_shadow_signature(http, make_webhook):
    wid = await make_webhook(
        secret=SECRET,
        headers={"x-setvault-signature": "forged", "content-type": "text/plain"})
    await _go(wid)
    req = http.requests[0]
    assert req.headers.get_list("X-SetVault-Signature") == [
        ws.sign(SECRET, int(req.headers["X-SetVault-Timestamp"]), req.content)]
    assert req.headers.get_list("Content-Type") == ["text/plain"]


async def test_stored_framing_headers_are_dropped(http, make_webhook):
    wid = await make_webhook(headers={"Content-Length": "1", "Host": "evil", "X-A": "1"})
    await _go(wid)
    req = http.requests[0]
    assert req.headers.get_list("Content-Length") == [str(len(req.content))]
    assert req.headers.get_list("Host") != ["evil"]
    assert req.headers["X-A"] == "1"


async def test_content_type_defaults_to_json_when_absent(http, make_webhook):
    wid = await make_webhook(headers={"X-A": "1"})
    await _go(wid)
    assert http.requests[0].headers.get_list("Content-Type") == ["application/json"]


async def test_undecryptable_headers_are_a_permanent_logged_failure(http, make_webhook):
    wid = await make_webhook()
    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(wid))
        row.encrypted_headers = Crypter("another-secret-key-0123456789").encrypt(b'{"A":"1"}')
        await s.commit()
    result = await _go(wid)  # must not raise RetryableDeliveryError
    assert http.requests == []
    assert "cannot decrypt" in result["error"]
    (d,) = await _deliveries(wid)
    assert d.status_code is None
    assert d.error == "cannot decrypt webhook headers/secret (SECRET_KEY changed?)"
    async with session_factory()() as s:
        got = await s.get(LibraryWebhook, uuid.UUID(wid))
        assert got.last_error == d.error


async def test_undecryptable_secret_is_a_permanent_logged_failure(http, make_webhook):
    wid = await make_webhook()
    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(wid))
        row.encrypted_secret = Crypter("another-secret-key-0123456789").encrypt(b"s")
        await s.commit()
    await _go(wid)
    assert http.requests == []
    (d,) = await _deliveries(wid)
    assert "cannot decrypt" in d.error


def _run_with_job(monkeypatch, job, fake):
    monkeypatch.setattr(wd, "dispatch_webhook", fake)
    monkeypatch.setattr(wd, "run_job", asyncio.run)
    monkeypatch.setattr(wd, "get_current_job", lambda: job)


def test_non_retrying_job_swallows_retryable_error(monkeypatch):
    async def fake(**kw):
        raise wd.RetryableDeliveryError(
            "HTTP 503", result={"status_code": 503, "error": "HTTP 503"})

    _run_with_job(monkeypatch, type("J", (), {"retries_left": None})(), fake)
    assert wd.run_dispatch_webhook(webhook_id="x", event="e", delivery_id="d") == {
        "status_code": 503, "error": "HTTP 503"}


def test_retrying_job_still_raises(monkeypatch):
    async def fake(**kw):
        raise wd.RetryableDeliveryError("HTTP 503")

    for left in (5, 0):
        _run_with_job(monkeypatch, type("J", (), {"retries_left": left})(), fake)
        with pytest.raises(wd.RetryableDeliveryError):
            wd.run_dispatch_webhook(webhook_id="x", event="e", delivery_id="d")


def test_delivery_id_is_optional_for_old_in_flight_jobs(monkeypatch):
    seen = []

    async def fake(**kw):
        seen.append(kw["delivery_id"])
        return {}

    _run_with_job(monkeypatch, None, fake)
    wd.run_dispatch_webhook(webhook_id="x", event="e")
    wd.run_dispatch_webhook(webhook_id="x", event="e", delivery_id="given")
    assert uuid.UUID(seen[0]).version == 4
    assert seen[1] == "given"

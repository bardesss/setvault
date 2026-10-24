async def test_system_info_returns_version(authed_admin_client):
    response = await authed_admin_client.get("/api/admin/system")
    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    # secrets must be filtered
    assert "secret_key" not in body["env"]


async def test_jobs_listing_is_admin_only(client, seeded_admin):
    response = await client.get("/api/admin/jobs")
    assert response.status_code in (401, 403)


async def test_jobs_api_returns_rq_id_and_started_at(authed_admin_client):
    from datetime import UTC, datetime, timedelta

    from setvault_core.db import session_factory
    from setvault_core.models.system import Job
    from sqlalchemy import delete

    started = datetime.now(UTC) - timedelta(seconds=5)
    async with session_factory()() as s:
        await s.execute(delete(Job).where(Job.rq_id == "api-test-rq"))
        for status in ("finished", "failed"):
            s.add(Job(rq_id="api-test-rq", kind="pipeline.run_pipeline", status=status,
                      message="ValueError: boom" if status == "failed" else None,
                      result={"ok": True} if status == "finished" else {},
                      started_at=started, finished_at=started + timedelta(seconds=2)))
        await s.commit()
    try:
        r = await authed_admin_client.get("/api/admin/jobs")
        assert r.status_code == 200, r.text
        rows = [j for j in r.json()["items"] if j["rq_id"] == "api-test-rq"]
        assert len(rows) == 2
        assert rows[0]["id"] != rows[1]["id"]
        by_status = {j["status"]: j for j in rows}
        assert by_status["failed"]["message"] == "ValueError: boom"
        assert by_status["finished"]["result"] == {"ok": True}
        for j in rows:
            assert j["kind"] == "pipeline.run_pipeline"
            assert datetime.fromisoformat(j["started_at"]) == started
            assert j["finished_at"] is not None
            assert j["created_at"] is not None
    finally:
        async with session_factory()() as s:
            await s.execute(delete(Job).where(Job.rq_id == "api-test-rq"))
            await s.commit()


async def test_users_listing_includes_admin(authed_admin_client):
    response = await authed_admin_client.get("/api/users")
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(u["email"] == "admin@example.test" for u in items)


async def test_remeasure_loudness_requires_admin(client):
    client.cookies.clear()
    r = await client.post("/api/admin/maintenance/remeasure-loudness")
    assert r.status_code in (401, 403)


async def test_remeasure_loudness_enqueues_backfill(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    import rq
    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet
    from sqlalchemy import update

    async with session_factory()() as s:
        await s.execute(update(LiveSet).where(LiveSet.slug == seeded_live_set["slug"])
                        .values(normalized_lufs=-70.0))
        await s.commit()

    enqueued: list[str] = []

    class _Job:
        id = "job-1"

    def _enqueue(self, func, **kwargs):
        enqueued.append(func)
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)
    r = await authed_admin_client.post("/api/admin/maintenance/remeasure-loudness")
    assert r.status_code == 202, r.text
    assert r.json() == {"status": "queued", "job_id": "job-1", "candidates": 1}
    assert enqueued == ["setvault_core.jobs.loudness_backfill.run_remeasure_bogus_loudness"]


async def test_settings_loudness_target_roundtrip_and_null_off(authed_admin_client):
    c = authed_admin_client
    before = (await c.get("/api/admin/settings")).json()["loudness_target_lufs"]
    try:
        r = await c.put("/api/admin/settings", json={"loudness_target_lufs": -16.5})
        assert r.status_code == 200, r.text
        assert r.json()["loudness_target_lufs"] == -16.5

        # Leaving the field out keeps the target.
        r = await c.put("/api/admin/settings", json={"quality_cutoff": "lossless"})
        assert r.status_code == 200, r.text
        assert (await c.get("/api/admin/settings")).json()["loudness_target_lufs"] == -16.5

        # An explicit null turns loudness matching off.
        r = await c.put("/api/admin/settings", json={"loudness_target_lufs": None})
        assert r.status_code == 200, r.text
        assert (await c.get("/api/admin/settings")).json()["loudness_target_lufs"] is None

        for bad in (-30.1, -4.9, "loud"):
            r = await c.put("/api/admin/settings", json={"loudness_target_lufs": bad})
            assert r.status_code == 422, (bad, r.text)
        for edge in (-30.0, -5.0):
            r = await c.put("/api/admin/settings", json={"loudness_target_lufs": edge})
            assert r.status_code == 200, (edge, r.text)
    finally:
        await c.put("/api/admin/settings", json={"loudness_target_lufs": before})


async def test_regain_endpoint_admin_only_and_audited(client, seeded_admin, monkeypatch):
    import rq
    from setvault_core.db import session_factory
    from setvault_core.models.identity import User
    from setvault_core.models.system import AuditEvent
    from setvault_core.services.passwords import hash_password
    from sqlalchemy import select

    enqueued: list[tuple[str, str, dict]] = []

    class _Job:
        id = "regain-job-1"

    def _enqueue(self, func, **kwargs):
        enqueued.append((self.name, func, kwargs))
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)

    async def _login(email: str) -> None:
        login = await client.post("/api/auth/login",
                                  json={"email": email, "password": "hunter2hunter2"})
        client.cookies = login.cookies
        client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]

    r = await client.post("/api/admin/maintenance/regain")
    assert r.status_code in (401, 403)
    async with session_factory()() as s:
        s.add(User(email="member-regain@x.test", username="member-regain", display_name="M",
                   password_hash=hash_password("hunter2hunter2"), role="member"))
        await s.commit()
    await _login("member-regain@x.test")
    assert (await client.post("/api/admin/maintenance/regain")).status_code == 403
    assert enqueued == []

    await _login("admin@example.test")
    r = await client.post("/api/admin/maintenance/regain")
    assert r.status_code == 202, r.text
    assert r.json() == {"job_id": "regain-job-1"}
    assert enqueued == [(
        "low", "setvault_core.jobs.regain.run_regain_library", {"job_timeout": "6h"},
    )]
    async with session_factory()() as s:
        rows = (await s.execute(
            select(AuditEvent).where(AuditEvent.action == "maintenance.regain_started")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].after == {"job_id": "regain-job-1"}


def _clear_scan_cache():
    from setvault_core.jobs import quality_backfill as qb

    redis = qb._redis()
    redis.delete(qb.SCAN_CACHE_KEY, qb.SCAN_JOB_KEY, qb.SCAN_LOCK_KEY)


async def test_quality_backfill_dry_run_counts(authed_admin_client, seeded_live_set):
    _clear_scan_cache()
    r = await authed_admin_client.get("/api/admin/maintenance/quality-backfill")
    assert r.status_code == 200, r.text
    # Never scanned: the duplicate figures are unknown, not zero.
    assert r.json() == {
        "to_fingerprint": 1, "to_measure": 1, "failed": 0,
        "duplicate_pairs": None, "duplicate_pairs_complete": None, "scanned_at": None,
    }


async def test_quality_backfill_get_does_not_scan(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    """The fingerprint comparison is CPU-bound: it runs in the worker, never
    in the API process on a page load."""
    from setvault_core.jobs import quality_backfill as qb
    from setvault_core.services import set_merge

    async def boom(*a, **kw):
        raise AssertionError("GET must not scan")

    monkeypatch.setattr(set_merge, "scan_duplicate_pairs", boom)
    monkeypatch.setattr(qb, "scan_duplicate_pairs", boom)
    _clear_scan_cache()
    r = await authed_admin_client.get("/api/admin/maintenance/quality-backfill")
    assert r.status_code == 200, r.text
    assert r.json()["to_fingerprint"] == 1


async def test_scan_post_enqueues_and_caches(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    import rq
    from setvault_core.jobs import quality_backfill as qb

    _clear_scan_cache()
    calls: list[tuple[str, str, dict]] = []

    class _Job:
        id = "job-scan"

    def _enqueue(self, func, **kwargs):
        calls.append((self.name, func, kwargs))
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)
    try:
        r = await authed_admin_client.post("/api/admin/maintenance/quality-backfill/scan")
        assert r.status_code == 202, r.text
        assert r.json() == {"job_id": "job-scan"}
        assert calls == [(
            "default", "setvault_core.jobs.quality_backfill.run_duplicate_scan",
            {"job_timeout": qb.DUPLICATE_SCAN_TIMEOUT},
        )]

        # The worker runs the job; the GET then serves its cached result.
        res = await qb._run_duplicate_scan()
        assert res["duplicate_pairs"] == 0 and res["duplicate_pairs_complete"] is True
        body = (await authed_admin_client.get("/api/admin/maintenance/quality-backfill")).json()
        assert body["duplicate_pairs"] == 0
        assert body["duplicate_pairs_complete"] is True
        assert body["scanned_at"] == res["scanned_at"]
    finally:
        _clear_scan_cache()


async def test_scan_post_is_admin_only(client, seeded_admin):
    client.cookies.clear()
    r = await client.post("/api/admin/maintenance/quality-backfill/scan")
    assert r.status_code in (401, 403)


async def test_quality_backfill_post_enqueues_with_timeout(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    import rq

    calls: list[tuple[str, dict]] = []

    class _Job:
        id = "job-q"

    def _enqueue(self, func, **kwargs):
        calls.append((func, kwargs))
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)
    r = await authed_admin_client.post("/api/admin/maintenance/quality-backfill")
    assert r.status_code == 202, r.text
    assert r.json() == {
        "status": "queued", "job_id": "job-q", "cleanup": False,
        "to_fingerprint": 1, "to_measure": 1, "failed": 0,
    }
    assert calls == [(
        "setvault_core.jobs.quality_backfill.run_quality_backfill", {"job_timeout": "1h"},
    )]


async def test_quality_backfill_post_with_cleanup_carries_job_state(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    import rq

    calls: list[tuple[str, dict]] = []

    class _Job:
        id = "job-c"

    def _enqueue(self, func, **kwargs):
        calls.append((func, kwargs))
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)
    r = await authed_admin_client.post(
        "/api/admin/maintenance/quality-backfill", json={"cleanup": True},
    )
    assert r.status_code == 202, r.text
    assert r.json()["cleanup"] is True
    ((func, kwargs),) = calls
    assert func == "setvault_core.jobs.quality_backfill.run_quality_backfill"
    assert kwargs["job_timeout"] == "1h"
    assert kwargs["kwargs"] == {
        "cleanup": True, "phase": "fill", "cursor": None,
        "counts": {
            "fingerprinted": 0, "measured": 0, "merged": 0, "skipped": 0, "errors": 0,
        },
    }


async def test_quality_backfill_retry_failed_clears_markers(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    import uuid
    from datetime import UTC, datetime

    import rq
    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet

    class _Job:
        id = "job-r"

    monkeypatch.setattr(rq.Queue, "enqueue", lambda self, func, **kw: _Job())
    sid = uuid.UUID(seeded_live_set["id"])
    for retry, expect_failed in ((False, 1), (True, 0)):
        async with session_factory()() as s:
            (await s.get(LiveSet, sid)).quality_backfill_failed_at = datetime.now(UTC)
            await s.commit()
        body = {"retry_failed": True} if retry else {}
        r = await authed_admin_client.post(
            "/api/admin/maintenance/quality-backfill", json=body,
        )
        assert r.status_code == 202, r.text
        assert r.json()["failed"] == expect_failed
        async with session_factory()() as s:
            live = await s.get(LiveSet, sid)
            assert (live.quality_backfill_failed_at is None) is retry


async def test_quality_backfill_post_while_running_says_already_running(
    authed_admin_client, seeded_live_set, monkeypatch,
):
    import uuid
    from datetime import UTC, datetime

    import rq
    from setvault_core.db import session_factory
    from setvault_core.jobs import quality_backfill as qb
    from setvault_core.models.catalog import LiveSet

    calls = []
    monkeypatch.setattr(rq.Queue, "enqueue", lambda self, func, **kw: calls.append(func))
    monkeypatch.setattr(qb, "quality_backfill_in_flight", lambda: True)
    sid = uuid.UUID(seeded_live_set["id"])
    async with session_factory()() as s:
        (await s.get(LiveSet, sid)).quality_backfill_failed_at = datetime.now(UTC)
        await s.commit()

    r = await authed_admin_client.post(
        "/api/admin/maintenance/quality-backfill",
        json={"retry_failed": True, "cleanup": True},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "already_running"}
    assert calls == []
    async with session_factory()() as s:
        # Nothing changes while a chain runs, failure markers included.
        assert (await s.get(LiveSet, sid)).quality_backfill_failed_at is not None


async def test_quality_backfill_member_forbidden(client, seeded_admin):
    from setvault_core.db import session_factory
    from setvault_core.models.identity import User
    from setvault_core.services.passwords import hash_password

    async with session_factory()() as s:
        s.add(User(email="member-qb@x.test", username="member-qb", display_name="M",
                   password_hash=hash_password("hunter2hunter2"), role="member"))
        await s.commit()
    login = await client.post("/api/auth/login",
                              json={"email": "member-qb@x.test", "password": "hunter2hunter2"})
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]
    assert (await client.get("/api/admin/maintenance/quality-backfill")).status_code == 403
    assert (await client.post("/api/admin/maintenance/quality-backfill")).status_code == 403

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

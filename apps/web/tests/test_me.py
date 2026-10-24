async def test_continue_listening_empty_for_new_user(authed_admin_client):
    response = await authed_admin_client.get("/api/me/continue-listening")
    assert response.status_code == 200
    assert response.json() == []


async def test_continue_listening_returns_in_progress_sets(
    authed_admin_client, seeded_live_set
):
    slug = seeded_live_set["slug"]
    put = await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 12.5, "completed": False},
    )
    assert put.status_code == 204
    response = await authed_admin_client.get("/api/me/continue-listening")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["slug"] == slug
    assert items[0]["position_seconds"] == 12.5


async def test_continue_listening_excludes_completed(
    authed_admin_client, seeded_live_set
):
    slug = seeded_live_set["slug"]
    await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 999.0, "completed": True},
    )
    response = await authed_admin_client.get("/api/me/continue-listening")
    assert response.status_code == 200
    assert response.json() == []


async def test_activity_returns_array(authed_admin_client):
    response = await authed_admin_client.get("/api/me/activity")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_me_endpoints_require_auth(client):
    response = await client.get("/api/me/continue-listening")
    assert response.status_code == 401


async def test_home_summary_requires_auth(client):
    response = await client.get("/api/me/home-summary")
    assert response.status_code == 401


async def test_home_summary_returns_zero_for_empty_vault(authed_admin_client):
    response = await authed_admin_client.get("/api/me/home-summary")
    assert response.status_code == 200
    body = response.json()
    assert body["sets_count"] == 0
    assert body["tracks_resolved_count"] == 0
    assert body["tracks_needing_ids_count"] == 0
    assert body["audio_bytes"] == 0
    assert body["deltas_window_days"] == 7
    assert body["sets_delta"] == 0
    assert body["tracks_resolved_delta"] == 0
    assert body["tracks_needing_ids_delta"] == 0


async def test_home_summary_counts_one_seeded_set(
    authed_admin_client, seeded_live_set
):
    response = await authed_admin_client.get("/api/me/home-summary")
    assert response.status_code == 200
    body = response.json()
    assert body["sets_count"] == 1
    assert body["audio_bytes"] == 0  # its sizes are not recorded yet


async def test_home_summary_audio_bytes_sums_sizes(authed_admin_client, seeded_live_set):
    import uuid
    from datetime import UTC, datetime

    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet

    # Set A: original and stream measured. Set B: not backfilled yet (NULL
    # sizes count as 0). A recycled set never counts.
    await _patch_live_set(seeded_live_set["id"], audio_bytes=100, stream_bytes=50)
    async with session_factory()() as s:
        a = await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))
        for name, extra in (
            ("b", {}),
            ("gone", {"audio_bytes": 1000, "stream_bytes": 1000,
                      "deleted_at": datetime.now(UTC)}),
        ):
            s.add(LiveSet(
                slug=f"size-{name}-{uuid.uuid4().hex[:6]}", title=name,
                media_root_id=a.media_root_id, audio_path=f"originals/{name}.flac",
                status="published", source_type="upload", uploaded_by=a.uploaded_by,
                **extra,
            ))
        await s.commit()

    response = await authed_admin_client.get("/api/me/home-summary")
    assert response.status_code == 200
    body = response.json()
    assert body["sets_count"] == 2
    assert body["audio_bytes"] == 150


async def _patch_live_set(set_id: str, **fields) -> None:
    import uuid

    from setvault_core.db import session_factory
    from setvault_core.models.catalog import LiveSet

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(set_id))
        for k, v in fields.items():
            setattr(live, k, v)
        await s.commit()


async def test_continue_listening_skips_position_zero(
    authed_admin_client, seeded_live_set
):
    slug = seeded_live_set["slug"]
    for pos in (0.0, 5.0):
        put = await authed_admin_client.put(
            f"/api/sets/{slug}/state",
            json={"position_seconds": pos, "completed": False},
        )
        assert put.status_code == 204
        response = await authed_admin_client.get("/api/me/continue-listening")
        assert response.status_code == 200
        assert response.json() == [], pos


async def test_continue_listening_skips_unpublished(
    authed_admin_client, seeded_live_set
):
    slug = seeded_live_set["slug"]
    put = await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 60.0, "completed": False},
    )
    assert put.status_code == 204
    await _patch_live_set(seeded_live_set["id"], status="draft")
    response = await authed_admin_client.get("/api/me/continue-listening")
    assert response.status_code == 200
    assert response.json() == []


async def test_continue_listening_skips_nearly_done(
    authed_admin_client, seeded_live_set
):
    slug = seeded_live_set["slug"]
    await _patch_live_set(seeded_live_set["id"], duration_seconds=1000)
    # 96 % is still in progress; 97 % counts as done.
    await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 960.0, "completed": False},
    )
    response = await authed_admin_client.get("/api/me/continue-listening")
    assert [i["slug"] for i in response.json()] == [slug]
    await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 970.0, "completed": False},
    )
    response = await authed_admin_client.get("/api/me/continue-listening")
    assert response.status_code == 200
    assert response.json() == []


async def _mint_rss(client) -> dict:
    response = await client.post("/api/me/rss-tokens", json={"name": "t"})
    assert response.status_code == 201
    return response.json()


async def test_rss_token_urls_are_absolute(authed_admin_client, monkeypatch):
    from setvault_web.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("BASE_URL", "http://sv.test:1970/")
    try:
        body = await _mint_rss(authed_admin_client)
        for key in ("favorites_url", "recent_url", "everything_url"):
            assert body[key].startswith("http://sv.test:1970/api/feed/")
        monkeypatch.setenv("BASE_URL", "")
        get_settings.cache_clear()
        body = await _mint_rss(authed_admin_client)
        for key in ("favorites_url", "recent_url", "everything_url"):
            assert body[key].startswith("/api/feed/")
    finally:
        get_settings.cache_clear()

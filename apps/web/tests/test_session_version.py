"""Session cookies carry ``User.session_version``; every cookie-auth surface
(API deps, /api/auth/me, stream, waveform, WS, tusd hook) must reject a cookie
whose version no longer matches the user row."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from itsdangerous import TimestampSigner
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from sqlalchemy import select


async def _bump_version(user_id: uuid.UUID) -> None:
    async with session_factory()() as s:
        row = await s.get(User, user_id)
        row.session_version = row.session_version + 1
        await s.commit()


async def _seed_media(seeded_live_set: dict) -> None:
    """Give the seeded set a streaming + waveform file so the endpoints reach
    their auth gate instead of returning 404."""
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(seeded_live_set["id"]))
        live.streaming_path = "stream/seed.opus"
        live.waveform_path = "waveform/seed.json"
        live.embed_allowed = False
        await s.commit()
        mr = (await s.execute(
            select(MediaRoot).where(MediaRoot.default_for_ingest.is_(True)),
        )).scalar_one()
        host_path = Path(mr.host_path)
    for rel, data in (("stream/seed.opus", b"\x00\x00"), ("waveform/seed.json", b"{}")):
        target = host_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


async def test_api_rejects_stale_version(authed_admin_client, seeded_admin):
    assert (await authed_admin_client.get("/api/auth/me")).status_code == 200
    await _bump_version(seeded_admin.id)
    r = await authed_admin_client.get("/api/auth/me")
    assert r.status_code == 401, r.text


async def test_current_user_dep_rejects_stale_version(authed_admin_client, seeded_admin):
    # /api/auth/logout is gated by deps.current_user.
    await _bump_version(seeded_admin.id)
    r = await authed_admin_client.post("/api/auth/logout")
    assert r.status_code == 401, r.text


async def test_stream_rejects_stale_version(authed_admin_client, seeded_admin, seeded_live_set):
    await _seed_media(seeded_live_set)
    url = f"/api/sets/{seeded_live_set['slug']}/stream"
    assert (await authed_admin_client.get(url)).status_code == 200
    await _bump_version(seeded_admin.id)
    r = await authed_admin_client.get(url)
    assert r.status_code == 401, r.text


async def test_waveform_rejects_stale_version(
    authed_admin_client, seeded_admin, seeded_live_set,
):
    await _seed_media(seeded_live_set)
    url = f"/api/sets/{seeded_live_set['slug']}/waveform"
    assert (await authed_admin_client.get(url)).status_code == 200
    await _bump_version(seeded_admin.id)
    r = await authed_admin_client.get(url)
    assert r.status_code == 401, r.text


async def test_stream_rejects_disabled_user(authed_admin_client, seeded_admin, seeded_live_set):
    await _seed_media(seeded_live_set)
    async with session_factory()() as s:
        row = await s.get(User, seeded_admin.id)
        row.disabled_at = datetime.now(UTC)
        await s.commit()
    r = await authed_admin_client.get(f"/api/sets/{seeded_live_set['slug']}/stream")
    assert r.status_code == 401, r.text


async def test_ws_rejects_stale_version(authed_admin_client, seeded_admin):
    from setvault_web.main import create_app
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    cookie = authed_admin_client.cookies.get("session")
    await _bump_version(seeded_admin.id)

    tc = TestClient(create_app(), base_url="https://test")
    tc.cookies.set("session", cookie)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with tc.websocket_connect(f"/ws/sets/{uuid.uuid4()}/progress"):
            pass
    assert exc_info.value.code == 1008


async def test_tusd_hook_rejects_stale_version(authed_admin_client, seeded_admin):
    cookie = authed_admin_client.cookies.get("session")
    await _bump_version(seeded_admin.id)
    r = await authed_admin_client.post(
        "/api/uploads/tusd-hooks",
        json={
            "Type": "pre-create",
            "Event": {
                "Upload": {"MetaData": {"filename": "set.flac"}},
                "HTTPRequest": {"Header": {"Cookie": [f"session={cookie}"]}},
            },
        },
    )
    assert r.status_code == 401, r.text


async def test_legacy_cookie_still_works(client, seeded_admin):
    from setvault_web.config import get_settings

    legacy = TimestampSigner(get_settings().secret_key, salt="setvault.session").sign(
        f"{seeded_admin.id}:legacynonce"
    ).decode("ascii")
    client.cookies.set("session", legacy)
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "admin@example.test"

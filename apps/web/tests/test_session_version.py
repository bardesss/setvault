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


# --- Revocation triggers -------------------------------------------------

_VICTIM_PW = "victim-password-123"


async def _make_victim_cookie() -> tuple[uuid.UUID, str]:
    """Create user U and return (id, a valid session cookie value for U)."""
    from setvault_core.services.passwords import hash_password
    from setvault_web.deps import get_signer

    async with session_factory()() as s:
        u = User(
            email="victim@example.test", username="victim", display_name="Victim",
            password_hash=hash_password(_VICTIM_PW), role="user",
        )
        s.add(u)
        await s.commit()
        uid = u.id
    from setvault_web.config import get_settings

    signer = get_signer(get_settings())
    return uid, signer.issue(str(uid), 0)


async def _status_with_cookie(cookie: str) -> int:
    from httpx import ASGITransport, AsyncClient
    from setvault_web.main import create_app

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test",
    ) as ac:
        ac.cookies.set("session", cookie)
        return (await ac.get("/api/auth/me")).status_code


async def test_disable_revokes_sessions(authed_admin_client):
    uid, cookie = await _make_victim_cookie()
    assert await _status_with_cookie(cookie) == 200
    r = await authed_admin_client.post(f"/api/users/{uid}/disable")
    assert r.status_code == 204, r.text
    assert await _status_with_cookie(cookie) == 401


async def test_reset_redeem_revokes_sessions(authed_admin_client, client):
    uid, cookie = await _make_victim_cookie()
    link = await authed_admin_client.post(
        "/api/password-reset/admin-link", json={"email": "victim@example.test"},
    )
    token = link.json()["reset_link"].rsplit("/", 1)[-1]
    # admin-link already revoked; re-issue a cookie at the current version.
    async with session_factory()() as s:
        ver = (await s.get(User, uid)).session_version
    from setvault_web.config import get_settings
    from setvault_web.deps import get_signer

    cookie = get_signer(get_settings()).issue(str(uid), ver)
    assert await _status_with_cookie(cookie) == 200
    r = await client.post(
        f"/api/password-reset/{token}/redeem", json={"password": "another-strong-pw-1"},
    )
    assert r.status_code == 204, r.text
    assert await _status_with_cookie(cookie) == 401


async def test_admin_link_revokes_sessions(authed_admin_client):
    _uid, cookie = await _make_victim_cookie()
    assert await _status_with_cookie(cookie) == 200
    r = await authed_admin_client.post(
        "/api/password-reset/admin-link", json={"email": "victim@example.test"},
    )
    assert r.status_code == 200, r.text
    assert await _status_with_cookie(cookie) == 401


async def test_own_password_change_signs_out_other_devices(client, seeded_admin):
    a = await client.post("/api/auth/login",
                          json={"email": "admin@example.test", "password": "hunter2hunter2"})
    b = await client.post("/api/auth/login",
                          json={"email": "admin@example.test", "password": "hunter2hunter2"})
    cookie_a, cookie_b = a.cookies["session"], b.cookies["session"]
    client.cookies.clear()
    client.cookies.set("session", cookie_a)
    client.headers["X-CSRF-Token"] = a.cookies["csrf_token"]
    client.cookies.set("csrf_token", a.cookies["csrf_token"])
    r = await client.post("/api/me/change-password", json={
        "current_password": "hunter2hunter2", "new_password": "brand-new-password-9",
    })
    assert r.status_code == 204, r.text
    new_cookie = r.cookies["session"]
    assert await _status_with_cookie(cookie_b) == 401
    assert await _status_with_cookie(cookie_a) == 401
    assert await _status_with_cookie(new_cookie) == 200

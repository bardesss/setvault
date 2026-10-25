"""Admin -> Sources -> YouTube cookies: upload, status, remove.

The cookie file is written under ``tmp_path`` by pointing
``SETVAULT_CONFIG_PATH`` at it.
"""
from __future__ import annotations

import pytest
from setvault_core.db import session_factory
from setvault_core.models.identity import User
from setvault_core.models.system import AuditEvent
from setvault_core.services.passwords import hash_password
from sqlalchemy import select

URL = "/api/admin/ytdlp-cookies"
SECRET = "s3cr3t-cookie-value"
GOOD = (
    "# Netscape HTTP Cookie File\n"
    f".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\t{SECRET}\n"
    f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tLOGIN_INFO\t{SECRET}\n"
    f".google.com\tTRUE\t/\tTRUE\t1893456000\tNID\t{SECRET}\n"
)


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SETVAULT_CONFIG_PATH", str(tmp_path))
    return tmp_path


async def _audit(action: str):
    async with session_factory()() as s:
        return (await s.execute(
            select(AuditEvent).where(AuditEvent.action == action)
        )).scalars().all()


async def _put(client, body: str | bytes):
    return await client.put(URL, content=body, headers={"Content-Type": "text/plain"})


async def test_status_when_unset(authed_admin_client, config_dir):
    r = await authed_admin_client.get(URL)
    assert r.status_code == 200, r.text
    assert r.json() == {"set": False, "uploaded_at": None, "youtube_cookies": 0}


async def test_upload_status_and_remove(authed_admin_client, config_dir):
    r = await _put(authed_admin_client, GOOD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["set"] is True
    assert body["youtube_cookies"] == 2
    assert body["uploaded_at"]
    assert SECRET not in r.text
    assert (config_dir / "youtube-cookies.txt").read_text() == GOOD

    r = await authed_admin_client.get(URL)
    assert r.json() == body
    assert SECRET not in r.text

    [event] = await _audit("ytdlp_cookies.uploaded")
    assert event.after == {"youtube_cookies": 2}
    assert SECRET not in str(event.before) + str(event.after)

    r = await authed_admin_client.delete(URL)
    assert r.status_code == 204
    assert not (config_dir / "youtube-cookies.txt").exists()
    assert (await authed_admin_client.get(URL)).json()["set"] is False
    assert len(await _audit("ytdlp_cookies.removed")) == 1


async def test_replace(authed_admin_client, config_dir):
    await _put(authed_admin_client, GOOD)
    one = ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tnew\n"
    r = await _put(authed_admin_client, one)
    assert r.status_code == 200, r.text
    assert r.json()["youtube_cookies"] == 1
    assert (config_dir / "youtube-cookies.txt").read_text() == one


async def test_remove_when_unset_is_404(authed_admin_client, config_dir):
    assert (await authed_admin_client.delete(URL)).status_code == 404


@pytest.mark.parametrize("body", [
    "",
    "hello world\n",
    '{"cookies": [{"name": "SID", "value": "s3cr3t-cookie-value"}]}',
    ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\n",
    f".google.com\tTRUE\t/\tTRUE\t0\tNID\t{SECRET}\n",
])
async def test_invalid_upload_is_400(authed_admin_client, config_dir, body):
    r = await _put(authed_admin_client, body)
    assert r.status_code == 400, r.text
    assert SECRET not in r.text
    assert not (config_dir / "youtube-cookies.txt").exists()
    assert await _audit("ytdlp_cookies.uploaded") == []


async def test_invalid_upload_keeps_the_previous_file(authed_admin_client, config_dir):
    await _put(authed_admin_client, GOOD)
    assert (await _put(authed_admin_client, "junk")).status_code == 400
    assert (config_dir / "youtube-cookies.txt").read_text() == GOOD


async def test_oversized_upload_is_400(authed_admin_client, config_dir):
    line = ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t" + "a" * 1000 + "\n"
    r = await _put(authed_admin_client, line * 1100)  # > 1 MB
    assert r.status_code == 400, r.text
    assert not (config_dir / "youtube-cookies.txt").exists()


async def test_non_admin_forbidden(client, seeded_admin, config_dir):
    (config_dir / "youtube-cookies.txt").write_text(GOOD)
    async with session_factory()() as s:
        s.add(User(email="member-cookies@x.test", username="member-cookies",
                   display_name="M", password_hash=hash_password("hunter2hunter2"),
                   role="member"))
        await s.commit()
    login = await client.post("/api/auth/login", json={
        "email": "member-cookies@x.test", "password": "hunter2hunter2"})
    assert login.status_code == 200
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]

    assert (await client.get(URL)).status_code == 403
    assert (await _put(client, GOOD)).status_code == 403
    assert (await client.delete(URL)).status_code == 403
    assert (config_dir / "youtube-cookies.txt").read_text() == GOOD


async def test_anonymous_unauthorized(client, config_dir):
    assert (await client.get(URL)).status_code in {401, 403}


async def test_bot_check_hint_in_rip_400(authed_admin_client, config_dir, monkeypatch):
    """Without cookies, the bot-check 400 says where to upload them."""
    import uuid
    from unittest.mock import MagicMock

    from setvault_core.services import url_rip as _service
    from yt_dlp.utils import DownloadError

    ctx = MagicMock()
    ctx.__enter__.return_value.extract_info.side_effect = DownloadError(
        "ERROR: [youtube] abc: Sign in to confirm you're not a bot."
    )
    monkeypatch.setattr(_service.yt_dlp, "YoutubeDL", MagicMock(return_value=ctx))
    r = await authed_admin_client.post(
        "/api/sets/url-rip",
        json={"url": f"https://www.youtube.com/watch?v={uuid.uuid4().hex[:11]}"},
    )
    assert r.status_code == 400, r.text
    assert "Admin → Sources → YouTube cookies" in r.json()["detail"]

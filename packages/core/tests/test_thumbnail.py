import io
import os
import uuid
from pathlib import Path

import httpx
import pytest
from PIL import Image
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import thumbnail
from setvault_core.jobs.thumbnail import THUMB_MAX_PX, store_thumbnail
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.services import remote_image
from setvault_core.services.remote_image import RemoteImageError, fetch_image


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), (255, 0, 0, 128)).save(buf, "PNG")
    return buf.getvalue()


async def _seed_set(tmp_path: Path) -> uuid.UUID:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="audio.flac", uploaded_by=u.id, source_type="url_rip",
                       status="draft")
        s.add(live)
        await s.commit()
        return live.id


def _mock_client(monkeypatch, handler) -> None:
    real = httpx.AsyncClient

    def _client(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(remote_image.httpx, "AsyncClient", _client)
    monkeypatch.setattr(remote_image, "is_blocked_host", lambda host: False)


async def test_store_thumbnail_writes_a_shrunk_jpeg(tmp_path, monkeypatch):
    sid = await _seed_set(tmp_path)
    body = _png(1920, 1080)

    async def _fetch(url):
        assert url == "https://i.ytimg.com/vi/x/maxresdefault.jpg"
        return body, "image/png"

    monkeypatch.setattr(thumbnail, "fetch_image", _fetch)
    assert await store_thumbnail(str(sid), "https://i.ytimg.com/vi/x/maxresdefault.jpg")

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.thumb_path == f"thumbs/{sid}.jpg"
    with Image.open(tmp_path / row.thumb_path) as img:
        assert img.format == "JPEG"
        assert max(img.size) == THUMB_MAX_PX


async def test_store_thumbnail_skips_a_broken_image(tmp_path, monkeypatch):
    sid = await _seed_set(tmp_path)

    async def _fetch(url):
        return b"<html>not an image</html>", "image/jpeg"

    monkeypatch.setattr(thumbnail, "fetch_image", _fetch)
    assert not await store_thumbnail(str(sid), "https://example.com/x.jpg")
    async with session_factory()() as s:
        assert (await s.get(LiveSet, sid)).thumb_path is None
    assert not (tmp_path / "thumbs" / f"{sid}.jpg").exists()


async def test_store_thumbnail_skips_a_failed_fetch(tmp_path, monkeypatch):
    sid = await _seed_set(tmp_path)

    async def _fetch(url):
        raise RemoteImageError("upstream fetch failed")

    monkeypatch.setattr(thumbnail, "fetch_image", _fetch)
    assert not await store_thumbnail(str(sid), "https://example.com/x.jpg")
    assert not await store_thumbnail(str(sid), None)


async def test_fetch_image_refuses_a_private_host():
    with pytest.raises(RemoteImageError, match="blocked"):
        await fetch_image("http://127.0.0.1/x.jpg")
    with pytest.raises(RemoteImageError, match="unsupported"):
        await fetch_image("file:///etc/passwd")


async def test_fetch_image_rejects_non_images_and_oversize(monkeypatch):
    def _handler(request):
        if request.url.path == "/page":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>")
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"location": "http://10.0.0.1/x.jpg"})
        return httpx.Response(200, headers={"content-type": "image/jpeg"},
                              content=b"\0" * (remote_image.MAX_IMAGE_BYTES + 1))

    _mock_client(monkeypatch, _handler)
    for path in ("/page", "/moved", "/huge"):
        with pytest.raises(RemoteImageError):
            await fetch_image(f"https://cdn.example.com{path}")


async def test_fetch_image_returns_body_and_type(monkeypatch):
    body = _png(4, 4)
    _mock_client(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "image/png; charset=binary"}, content=body))
    assert await fetch_image("https://cdn.example.com/a.png") == (body, "image/png")

import asyncio
import time

from setvault_web import main as web_main


async def test_health_ok_body_only_status(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_no_base_url_or_version(client):
    body = (await client.get("/api/health")).json()
    assert "version" not in body
    assert "base_url" not in body


async def test_health_redis_down_503(client, monkeypatch):
    async def hang() -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr(web_main, "_ping_redis", hang)
    start = time.monotonic()
    response = await client.get("/api/health")
    assert time.monotonic() - start < 3
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "failed": ["redis"]}


async def test_health_redis_error_503(client, monkeypatch):
    async def boom() -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(web_main, "_ping_redis", boom)
    response = await client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["failed"] == ["redis"]


async def test_health_db_down_503(client, monkeypatch):
    async def boom() -> None:
        raise ConnectionError("db down")

    monkeypatch.setattr(web_main, "_check_db", boom)
    response = await client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "failed": ["db"]}

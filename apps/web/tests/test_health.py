import asyncio
import logging
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


async def test_health_unreachable_redis_503(client, monkeypatch):
    class _Settings:
        redis_url = "redis://127.0.0.1:1/0"

    monkeypatch.setattr(web_main, "get_settings", lambda: _Settings())
    start = time.monotonic()
    response = await client.get("/api/health")
    assert time.monotonic() - start < 3
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "failed": ["redis"]}


async def test_health_logs_warning_on_failure(client, monkeypatch, caplog):
    async def boom() -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(web_main, "_ping_redis", boom)
    with caplog.at_level(logging.WARNING, logger="setvault_web.main"):
        await client.get("/api/health")
    records = [r for r in caplog.records if r.name == "setvault_web.main"]
    assert len(records) == 1
    assert "redis" in records[0].getMessage()
    assert records[0].exc_info is not None


async def test_health_silent_on_success(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="setvault_web.main"):
        await client.get("/api/health")
    assert [r for r in caplog.records if r.name == "setvault_web.main"] == []

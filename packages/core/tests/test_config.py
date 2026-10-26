from __future__ import annotations

from setvault_core.config import DEFAULT_REDIS_URL, redis_url


def test_redis_url_reads_env_each_call(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert redis_url() == DEFAULT_REDIS_URL
    monkeypatch.setenv("REDIS_URL", "redis://x:1/2")
    assert redis_url() == "redis://x:1/2"
    monkeypatch.setenv("REDIS_URL", "redis://y:3/4")
    assert redis_url() == "redis://y:3/4"

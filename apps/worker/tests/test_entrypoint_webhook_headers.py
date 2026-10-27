import logging

from setvault_worker import entrypoint


def test_migrate_webhook_headers_calls_the_service(monkeypatch):
    calls = []

    async def fake(session, crypter):
        calls.append(crypter)
        return 3

    committed = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            committed.append(True)

    monkeypatch.setattr(entrypoint.webhook_security, "migrate_plaintext_headers", fake)
    monkeypatch.setattr(entrypoint, "async_sessionmaker", lambda engine: FakeSession)
    entrypoint._migrate_webhook_headers(
        "postgresql+asyncpg://u:p@localhost/none", "k" * 32)
    assert len(calls) == 1
    assert committed == [True]


def test_migrate_webhook_headers_swallows_errors(monkeypatch, caplog):
    async def boom(session, crypter):
        raise RuntimeError("db down")

    monkeypatch.setattr(entrypoint.webhook_security, "migrate_plaintext_headers", boom)
    with caplog.at_level(logging.ERROR):
        entrypoint._migrate_webhook_headers(
            "postgresql+asyncpg://u:p@localhost:1/none", "k" * 32)
    assert "webhook headers" in caplog.text

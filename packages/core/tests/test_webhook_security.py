import hmac
import os
import subprocess
import sys
import uuid
from hashlib import sha256
from pathlib import Path

import pytest
from setvault_core.models.library_webhook import LibraryWebhook
from setvault_core.services import webhook_security as ws
from setvault_core.services.crypto import Crypter
from sqlalchemy import delete, select

KEY = "k" * 32
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def crypter() -> Crypter:
    return Crypter(KEY)


def _row(**kw) -> LibraryWebhook:
    return LibraryWebhook(name=f"w{uuid.uuid4().hex[:6]}", target_url="https://x.test/h",
                          events=[], **kw)


def test_sign_is_hmac_of_timestamp_dot_body():
    got = ws.sign("s3cret", 1700000000, b'{"a":1}')
    want = "sha256=" + hmac.new(b"s3cret", b'1700000000.{"a":1}', sha256).hexdigest()
    assert got == want


def test_known_events():
    assert ws.KNOWN_EVENTS == ("set.published", "set.updated", "set.deleted",
                               "set.restored", "set.purged")


def test_headers_round_trip_encrypted(crypter):
    row = _row(headers={"legacy": "x"})
    ws.set_headers(row, {"X-Plex-Token": "abc"}, crypter)
    assert row.headers == {}
    assert b"abc" not in row.encrypted_headers
    assert ws.get_headers(row, crypter) == {"X-Plex-Token": "abc"}


def test_set_headers_empty_stores_none(crypter):
    row = _row()
    ws.set_headers(row, {}, crypter)
    assert row.encrypted_headers is None
    assert ws.get_headers(row, crypter) == {}


def test_load_headers_falls_back_to_legacy_plaintext(crypter):
    row = _row(headers={"A": "1"}, encrypted_headers=None)
    assert ws.get_headers(row, crypter) == {"A": "1"}


def test_secret_round_trip(crypter):
    secret = ws.generate_secret()
    assert len(secret) >= 43
    row = _row()
    assert ws.get_secret(row, crypter) is None
    ws.set_secret(row, secret, crypter)
    assert secret.encode() not in row.encrypted_secret
    assert ws.get_secret(row, crypter) == secret


async def test_migrate_plaintext_headers_is_idempotent(session, crypter):
    await session.execute(delete(LibraryWebhook))
    legacy1 = _row(headers={"A": "1"})
    legacy2 = _row(headers={"B": "2", "C": "3"})
    done = _row()
    ws.set_headers(done, {"D": "4"}, crypter)
    empty = _row(headers={})
    session.add_all([legacy1, legacy2, done, empty])
    await session.flush()

    assert await ws.migrate_plaintext_headers(session, crypter) == 2
    assert await ws.migrate_plaintext_headers(session, crypter) == 0
    rows = (await session.execute(select(LibraryWebhook))).scalars().all()
    assert all(r.headers == {} for r in rows)
    assert ws.get_headers(legacy1, crypter) == {"A": "1"}
    assert ws.get_headers(legacy2, crypter) == {"B": "2", "C": "3"}
    assert ws.get_headers(done, crypter) == {"D": "4"}


def test_migration_0036_round_trips():
    admin = os.environ["TEST_DATABASE_URL"].rsplit("/", 1)[0]
    name = f"setvault_mig0036_{uuid.uuid4().hex[:8]}"
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def _ddl(sql: str) -> None:
        eng = create_async_engine(admin + "/postgres", isolation_level="AUTOCOMMIT")
        async with eng.connect() as c:
            await c.exec_driver_sql(sql)
        await eng.dispose()

    asyncio.run(_ddl(f'create database "{name}"'))
    env = {**os.environ, "DATABASE_URL": f"{admin}/{name}"}
    try:
        for args in (["upgrade", "head"], ["downgrade", "-1"], ["upgrade", "head"]):
            r = subprocess.run(  # noqa: S603 — fixed argv
                [sys.executable, "-m", "alembic", *args], env=env,
                capture_output=True, text=True, cwd=REPO_ROOT)
            assert r.returncode == 0, r.stderr
    finally:
        asyncio.run(_ddl(f'drop database if exists "{name}" with (force)'))

"""Tests for the admin backup endpoint + the restore CLI (B3).

Auth tests stub out ``pg_dump`` so they don't need the real client tools.
The DB round-trip test is skipped unless both ``pg_dump`` and ``psql`` are on
PATH (CI has them; some dev hosts don't).
"""

from __future__ import annotations

import io
import os
import shutil
import tarfile
import uuid

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import MediaRoot
from setvault_web.restore import (
    MediaRootSpec,
    RestoreError,
    libpq_url_from_sqlalchemy,
    restore_from_tar,
)
from sqlalchemy import select, text

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault",
)

HAVE_PG_TOOLS = shutil.which("pg_dump") is not None and shutil.which("psql") is not None


# --------------------------------------------------------------------------- #
# Auth — anonymous + non-admin rejected, admin allowed (pg_dump stubbed out)
# --------------------------------------------------------------------------- #


def _stub_pg_dump(monkeypatch):
    """Replace the real pg_dump subprocess with a deterministic byte stream."""
    import setvault_web.api.backup as backup_mod

    def fake_stream(database_url):
        yield b"-- fake pg_dump output\nSELECT 1;\n"

    monkeypatch.setattr(backup_mod, "_stream_pg_dump", fake_stream)


async def test_backup_anonymous_rejected(client, seeded_admin):
    response = await client.get("/api/admin/backup")
    assert response.status_code in (401, 403)


async def test_backup_non_admin_rejected(client, seeded_admin):
    # Seed a plain member user, log in, and confirm the admin-only endpoint
    # returns 403 even with a valid (non-admin) session.
    from setvault_core.models.identity import User
    from setvault_core.services.passwords import hash_password

    init_engine(TEST_DB_URL)
    async with session_factory()() as s:
        s.add(
            User(
                email="member@x.test",
                username="member-backup",
                display_name="Member",
                password_hash=hash_password("hunter2hunter2"),
                role="member",
            )
        )
        await s.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": "member@x.test", "password": "hunter2hunter2"},
    )
    assert login.status_code == 200
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]

    response = await client.get("/api/admin/backup")
    assert response.status_code == 403


async def test_backup_admin_streams_tar(authed_admin_client, monkeypatch):
    _stub_pg_dump(monkeypatch)
    response = await authed_admin_client.get("/api/admin/backup")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-tar"
    assert "attachment" in response.headers["content-disposition"]
    assert "no-store" in response.headers["cache-control"]

    # Body is a valid tar containing db.sql with the stubbed content.
    tar = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:*")
    names = tar.getnames()
    assert "db.sql" in names
    extracted = tar.extractfile("db.sql").read()
    assert extracted == b"-- fake pg_dump output\nSELECT 1;\n"


async def test_backup_response_is_no_store(authed_admin_client, monkeypatch):
    _stub_pg_dump(monkeypatch)
    response = await authed_admin_client.get("/api/admin/backup")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]


# --------------------------------------------------------------------------- #
# restore_from_tar — unit tests that don't need real pg tools
# --------------------------------------------------------------------------- #


def test_libpq_url_translation():
    assert (
        libpq_url_from_sqlalchemy(
            "postgresql+asyncpg://u:p@h:5432/db"
        )
        == "postgresql://u:p@h:5432/db"
    )
    # plain postgres scheme is normalised + left otherwise intact
    assert (
        libpq_url_from_sqlalchemy("postgres://u:p@h/db") == "postgresql://u:p@h/db"
    )
    # no driver suffix -> unchanged host/userinfo
    assert (
        libpq_url_from_sqlalchemy("postgresql://u@h/db") == "postgresql://u@h/db"
    )


def _build_backup_tar(tmp_path, *, root_name="primary", include_db=True):
    """Hand-build a tar matching backup._stream_tar's member-path scheme."""
    tar_path = tmp_path / "backup.tar"
    with tarfile.open(tar_path, mode="w") as tar:
        if include_db:
            data = b"-- db\nSELECT 1;\n"
            info = tarfile.TarInfo(name="db.sql")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        # audio/<root_name>/sub/file.flac
        payload = b"FAKEFLAC"
        info = tarfile.TarInfo(name=f"audio/{root_name}/sub/track.flac")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return tar_path


def test_restore_requires_confirmation(tmp_path):
    tar_path = _build_backup_tar(tmp_path)
    dest = tmp_path / "media"
    with pytest.raises(RestoreError, match="not confirmed"):
        restore_from_tar(
            tar_path,
            TEST_DB_URL,
            [MediaRootSpec(name="primary", host_path=str(dest))],
            confirm=False,
        )
    # nothing copied
    assert not dest.exists()


def test_restore_media_copy_is_inverse_of_backup(tmp_path, monkeypatch):
    """A file archived as audio/<root>/sub/track.flac lands at
    <host_path>/sub/track.flac — the exact inverse of backup's layout."""
    # Stub the DB restore so the test needs no psql.
    import setvault_web.restore as restore_mod

    monkeypatch.setattr(restore_mod, "_restore_database", lambda db_sql, url: None)

    tar_path = _build_backup_tar(tmp_path, root_name="primary")
    dest = tmp_path / "media-dest"
    result = restore_from_tar(
        tar_path,
        TEST_DB_URL,
        [MediaRootSpec(name="primary", host_path=str(dest))],
        confirm=True,
    )
    assert result["media_files"] == 1
    restored = dest / "sub" / "track.flac"
    assert restored.is_file()
    assert restored.read_bytes() == b"FAKEFLAC"


def test_restore_rejects_missing_db_sql(tmp_path, monkeypatch):
    import setvault_web.restore as restore_mod

    monkeypatch.setattr(restore_mod, "_restore_database", lambda db_sql, url: None)
    tar_path = _build_backup_tar(tmp_path, include_db=False)
    with pytest.raises(RestoreError, match=r"missing db\.sql"):
        restore_from_tar(
            tar_path,
            TEST_DB_URL,
            [MediaRootSpec(name="primary", host_path=str(tmp_path / "m"))],
            confirm=True,
        )


# --------------------------------------------------------------------------- #
# Full DB round-trip — requires real pg_dump + psql
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not HAVE_PG_TOOLS,
    reason="pg_dump/psql not on PATH; round-trip exercised in CI (Linux)",
)
async def test_backup_restore_round_trip(client, tmp_path):
    """Seed a MediaRoot row, take a real backup, delete the row, restore, and
    assert the row is back."""
    from setvault_web.api.backup import _stream_tar

    init_engine(TEST_DB_URL)

    marker = f"roundtrip-{uuid.uuid4().hex[:8]}"
    media_dir = tmp_path / "media-src"
    media_dir.mkdir()
    (media_dir / "hello.txt").write_bytes(b"hi")

    # Seed a MediaRoot row (the thing we'll assert survives the round-trip).
    async with session_factory()() as s:
        root = MediaRoot(name=marker, host_path=str(media_dir))
        s.add(root)
        await s.commit()
        roots = list(
            (await s.execute(select(MediaRoot).order_by(MediaRoot.created_at)))
            .scalars()
            .all()
        )

    # Take a backup into a tar file (uses the real pg_dump via _stream_tar).
    tar_path = tmp_path / "rt.tar"
    with tar_path.open("wb") as fp:
        for chunk in _stream_tar(TEST_DB_URL, roots):
            fp.write(chunk)
    assert tar_path.stat().st_size > 0

    # Drop the row so we can prove restore brings it back.
    async with session_factory()() as s:
        await s.execute(text("DELETE FROM media_roots WHERE name = :n"), {"n": marker})
        await s.commit()
        gone = (
            await s.execute(select(MediaRoot).where(MediaRoot.name == marker))
        ).scalar_one_or_none()
        assert gone is None

    # Restore (DB load + media copy). Media goes back under the recorded path.
    restore_dest = tmp_path / "media-restored"
    restore_from_tar(
        tar_path,
        TEST_DB_URL,
        [MediaRootSpec(name=marker, host_path=str(restore_dest))],
        confirm=True,
    )

    # The pg_dump used --no-owner --no-privileges and the dump includes the
    # full table contents, so the row is back.
    init_engine(TEST_DB_URL)
    async with session_factory()() as s:
        back = (
            await s.execute(select(MediaRoot).where(MediaRoot.name == marker))
        ).scalar_one_or_none()
        assert back is not None

    # Cleanup the row we created.
    async with session_factory()() as s:
        await s.execute(text("DELETE FROM media_roots WHERE name = :n"), {"n": marker})
        await s.commit()

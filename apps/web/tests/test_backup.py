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
# restore CLI (main) — unit tests that don't need real pg tools
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


def _patch_restore_cli(monkeypatch, media_roots):
    """Point the restore CLI at the test DB and a fixed set of media roots
    (normally read back from the freshly restored DB)."""
    from types import SimpleNamespace

    import setvault_web.restore as restore_mod

    monkeypatch.setattr(
        restore_mod, "get_settings", lambda: SimpleNamespace(database_url=TEST_DB_URL),
    )

    async def fake_load_media_roots(url):
        return media_roots

    monkeypatch.setattr(restore_mod, "_load_media_roots", fake_load_media_roots)
    return restore_mod


def test_restore_requires_confirmation(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RESTORE_CONFIRM", raising=False)
    dest = tmp_path / "media"
    restore_mod = _patch_restore_cli(
        monkeypatch, [MediaRootSpec(name="primary", host_path=str(dest))],
    )
    monkeypatch.setattr(restore_mod, "_restore_database",
                        lambda db_sql, url: pytest.fail("restored without --yes"))
    tar_path = _build_backup_tar(tmp_path)

    with pytest.raises(SystemExit) as exc:
        restore_mod.main([str(tar_path)])
    assert exc.value.code == 2
    assert "without confirmation" in capsys.readouterr().err
    # nothing copied
    assert not dest.exists()


def test_restore_media_copy_is_inverse_of_backup(tmp_path, monkeypatch):
    """A file archived as audio/<root>/sub/track.flac lands at
    <host_path>/sub/track.flac — the exact inverse of backup's layout."""
    dest = tmp_path / "media-dest"
    restore_mod = _patch_restore_cli(
        monkeypatch, [MediaRootSpec(name="primary", host_path=str(dest))],
    )
    # Stub the DB restore so the test needs no psql.
    monkeypatch.setattr(restore_mod, "_restore_database", lambda db_sql, url: None)

    tar_path = _build_backup_tar(tmp_path, root_name="primary")
    restore_mod.main([str(tar_path), "--yes"])

    restored = dest / "sub" / "track.flac"
    assert restored.is_file()
    assert restored.read_bytes() == b"FAKEFLAC"
    assert [p for p in dest.rglob("*") if p.is_file()] == [restored]


def test_restore_rejects_missing_db_sql(tmp_path, monkeypatch, capsys):
    restore_mod = _patch_restore_cli(
        monkeypatch, [MediaRootSpec(name="primary", host_path=str(tmp_path / "m"))],
    )
    monkeypatch.setattr(restore_mod, "_restore_database", lambda db_sql, url: None)
    tar_path = _build_backup_tar(tmp_path, include_db=False)

    with pytest.raises(SystemExit) as exc:
        restore_mod.main([str(tar_path), "--yes"])
    assert exc.value.code == 1
    assert "missing db.sql" in capsys.readouterr().err


def test_restore_accepts_sql_gz(tmp_path, monkeypatch):
    """A scheduled ``.sql.gz`` backup restores the database only."""
    import gzip

    import setvault_web.restore as restore_mod

    loaded = []

    def fake_restore(db_sql, url):
        loaded.append((db_sql.name, db_sql.read_bytes(), url))

    monkeypatch.setattr(restore_mod, "_restore_database", fake_restore)
    monkeypatch.setattr(restore_mod, "_restore_media",
                        lambda *a: pytest.fail("a .sql.gz has no media"))
    gz = tmp_path / "setvault-20261023-033000.sql.gz"
    gz.write_bytes(gzip.compress(b"-- db\nSELECT 1;\n"))

    with pytest.raises(RestoreError, match="not confirmed"):
        restore_mod.restore_from_sql_gz(gz, TEST_DB_URL, confirm=False)
    assert loaded == []

    restore_mod.restore_from_sql_gz(gz, TEST_DB_URL, confirm=True)
    assert loaded == [("db.sql", b"-- db\nSELECT 1;\n", TEST_DB_URL)]

    # The CLI picks the DB-only path from the extension.
    loaded.clear()
    monkeypatch.setattr(restore_mod, "_load_media_roots",
                        lambda url: pytest.fail("no media to place"))
    restore_mod.main([str(gz), "--yes"])
    assert [(name, data) for name, data, _ in loaded] == [("db.sql", b"-- db\nSELECT 1;\n")]


def test_restore_rejects_corrupt_sql_gz(tmp_path, monkeypatch):
    import setvault_web.restore as restore_mod

    monkeypatch.setattr(restore_mod, "_restore_database",
                        lambda db_sql, url: pytest.fail("loaded a corrupt dump"))
    gz = tmp_path / "setvault-20261023-033000.sql.gz"
    gz.write_bytes(b"not gzip at all")
    with pytest.raises(RestoreError, match="not a valid gzip"):
        restore_mod.restore_from_sql_gz(gz, TEST_DB_URL, confirm=True)


# --------------------------------------------------------------------------- #
# Full DB round-trip — requires real pg_dump + psql
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not HAVE_PG_TOOLS,
    reason="pg_dump/psql not on PATH; round-trip exercised in CI (Linux)",
)
async def test_backup_restore_round_trip(client, tmp_path, monkeypatch):
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
    restore_mod = _patch_restore_cli(
        monkeypatch, [MediaRootSpec(name=marker, host_path=str(restore_dest))],
    )
    restore_mod.main([str(tar_path), "--yes"])

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

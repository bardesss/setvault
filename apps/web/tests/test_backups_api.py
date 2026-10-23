"""Admin -> Backups API (P2a A5): list, run now, download, delete, settings.

Backup files are written under ``tmp_path`` by pointing ``backup_dir`` at it;
the worker job is never run here (``Queue.enqueue`` is stubbed).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from setvault_core.db import session_factory
from setvault_core.models.identity import User
from setvault_core.models.system import AuditEvent
from setvault_core.services.passwords import hash_password
from setvault_core.services.system_config import get_config
from sqlalchemy import select

NAME = "setvault-20261023-033000.sql.gz"
_FIELDS = (
    "backup_enabled", "backup_time", "backup_keep", "backup_dir",
    "last_backup_at", "last_backup_status", "last_backup_error", "last_backup_bytes",
)


@pytest.fixture
async def backup_dir(tmp_path):
    async with session_factory()() as s:
        cfg = await get_config(s)
        saved = {f: getattr(cfg, f) for f in _FIELDS}
        cfg.backup_dir = str(tmp_path)
        cfg.last_backup_at = datetime(2026, 10, 23, 3, 30, tzinfo=UTC)
        cfg.last_backup_status = "failed"
        cfg.last_backup_error = "disk full"
        cfg.last_backup_bytes = 1234
        await s.commit()
    yield tmp_path
    async with session_factory()() as s:
        cfg = await get_config(s)
        for f, v in saved.items():
            setattr(cfg, f, v)
        await s.commit()


async def _audit(action: str):
    async with session_factory()() as s:
        return (await s.execute(
            select(AuditEvent).where(AuditEvent.action == action)
        )).scalars().all()


async def test_list_shape(authed_admin_client, backup_dir):
    (backup_dir / NAME).write_bytes(b"x" * 10)
    (backup_dir / "setvault-20261022-033000.sql.gz").write_bytes(b"y" * 5)
    day_old = datetime.now(UTC).timestamp() - 86400
    os.utime(backup_dir / "setvault-20261022-033000.sql.gz", (day_old, day_old))
    (backup_dir / "notes.txt").write_text("not a backup")
    (backup_dir / f"{NAME}.tmp").write_bytes(b"in progress")

    r = await authed_admin_client.get("/api/admin/backups")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dir"] == str(backup_dir)
    assert isinstance(body["dir_persistent"], bool)
    assert isinstance(body["tz"], str) and body["tz"]
    assert [f["name"] for f in body["files"]] == [NAME, "setvault-20261022-033000.sql.gz"]
    assert body["files"][0]["bytes"] == 10
    assert datetime.fromisoformat(body["files"][0]["created_at"])
    assert body["last"] == {
        "at": "2026-10-23T03:30:00+00:00", "status": "failed",
        "error": "disk full", "bytes": 1234,
    }


async def test_list_missing_dir_is_empty(authed_admin_client, backup_dir):
    async with session_factory()() as s:
        cfg = await get_config(s)
        cfg.backup_dir = str(backup_dir / "not-yet")
        await s.commit()
    r = await authed_admin_client.get("/api/admin/backups")
    assert r.status_code == 200, r.text
    assert r.json()["files"] == []
    assert r.json()["dir_error"] is None


async def test_list_unreadable_dir_reports_error(authed_admin_client, backup_dir, monkeypatch):
    from pathlib import Path

    def _denied(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "iterdir", _denied)
    r = await authed_admin_client.get("/api/admin/backups")
    assert r.status_code == 200, r.text
    assert r.json()["files"] == []
    assert r.json()["dir_error"] == "Permission denied"


def test_dir_persistent(monkeypatch):
    from setvault_web.api import backups

    monkeypatch.setattr(backups.os.path, "ismount", lambda p: False)
    assert backups.dir_persistent("/data/backups") is True
    assert backups.dir_persistent("/data") is True
    assert backups.dir_persistent("/database/backups") is False
    assert backups.dir_persistent("/srv/backups") is False
    # ".." is resolved before the /data check.
    assert backups.dir_persistent("/data/../tmp/x") is False
    assert backups.dir_persistent("/data/./backups/") is True
    mounts = {"/srv/backups"}
    monkeypatch.setattr(backups.os.path, "ismount",
                        lambda p: str(p).replace("\\", "/") in mounts)
    assert backups.dir_persistent("/srv/backups") is True
    assert backups.dir_persistent("/srv/backups/nightly") is True
    # The filesystem root is always a mount; it doesn't count.
    mounts = {"/"}
    assert backups.dir_persistent("/srv/backups") is False


async def test_run_enqueues_and_audits(authed_admin_client, backup_dir, monkeypatch):
    import rq

    enqueued = []

    class _Job:
        id = "backup-job-1"

    def _enqueue(self, func, **kwargs):
        enqueued.append((self.name, func, kwargs))
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)
    r = await authed_admin_client.post("/api/admin/backups/run")
    assert r.status_code == 202, r.text
    assert r.json() == {"job_id": "backup-job-1"}
    assert enqueued == [(
        "default", "setvault_core.jobs.backup.run_backup",
        {"kwargs": {"force": True}, "job_timeout": "2h"},
    )]
    rows = await _audit("backup.run_requested")
    assert len(rows) == 1 and rows[0].after == {"job_id": "backup-job-1"}


async def test_download_is_no_store(authed_admin_client, backup_dir):
    (backup_dir / NAME).write_bytes(b"gzdata")
    r = await authed_admin_client.get(f"/api/admin/backups/{NAME}")
    assert r.status_code == 200, r.text
    assert r.content == b"gzdata"
    assert r.headers["cache-control"] == "no-store"
    assert "attachment" in r.headers["content-disposition"]
    assert NAME in r.headers["content-disposition"]


@pytest.mark.parametrize("name", [
    "..%2Fetc%2Fpasswd",
    "..%2F..%2F..%2Fetc%2Fpasswd",
    "setvault-x.sql.gz",
    f"{NAME}.tmp",
    "setvault-20261023-033000.sql.gz.bak",
])
async def test_download_rejects_bad_names(authed_admin_client, backup_dir, name):
    (backup_dir / f"{NAME}.tmp").write_bytes(b"x")
    (backup_dir / "setvault-x.sql.gz").write_bytes(b"x")
    r = await authed_admin_client.get(f"/api/admin/backups/{name}")
    assert r.status_code == 404, (name, r.status_code)
    r = await authed_admin_client.delete(f"/api/admin/backups/{name}")
    # An encoded slash never reaches the handler (no route: 405 for DELETE).
    expected = (404, 405) if "%2F" in name else (404,)
    assert r.status_code in expected, (name, r.status_code)
    assert (backup_dir / "setvault-x.sql.gz").exists()
    assert (backup_dir / f"{NAME}.tmp").exists()


async def test_download_traversal_path(authed_admin_client, backup_dir):
    r = await authed_admin_client.get("/api/admin/backups/../etc/passwd")
    assert r.status_code == 404


def test_backup_file_rejects_traversal_names(tmp_path):
    """The name check itself, for names a router might hand through."""
    from fastapi import HTTPException
    from setvault_web.api import backups

    class Cfg:
        backup_dir = str(tmp_path / "b")

    (tmp_path / "b").mkdir()
    (tmp_path / "secret").write_text("x")
    for name in ("../secret", "..\\secret", f"../b/{NAME}", "/etc/passwd"):
        with pytest.raises(HTTPException) as exc:
            backups._backup_file(name, Cfg())
        assert exc.value.status_code == 404


async def test_delete_of_a_vanished_file_is_404(
    authed_admin_client, backup_dir, monkeypatch,
):
    """A prune between the name check and the delete gives 404, not 500."""
    from setvault_web.api import backups

    (backup_dir / NAME).write_bytes(b"x")
    real = backups._backup_file

    def vanishing(name, cfg):
        path = real(name, cfg)
        path.unlink()
        return path

    monkeypatch.setattr(backups, "_backup_file", vanishing)
    r = await authed_admin_client.delete(f"/api/admin/backups/{NAME}")
    assert r.status_code == 404, r.text
    assert await _audit("backup.deleted") == []


async def test_download_missing_file_404(authed_admin_client, backup_dir):
    r = await authed_admin_client.get(f"/api/admin/backups/{NAME}")
    assert r.status_code == 404


async def test_delete_removes_and_audits(authed_admin_client, backup_dir):
    (backup_dir / NAME).write_bytes(b"x" * 7)
    r = await authed_admin_client.delete(f"/api/admin/backups/{NAME}")
    assert r.status_code == 204, r.text
    assert not (backup_dir / NAME).exists()
    rows = await _audit("backup.deleted")
    assert len(rows) == 1
    assert rows[0].target_type == "backup" and rows[0].target_id == NAME
    assert rows[0].before == {"name": NAME, "bytes": 7}


async def test_non_admin_forbidden(client, seeded_admin, backup_dir, monkeypatch):
    import rq

    monkeypatch.setattr(rq.Queue, "enqueue", lambda *a, **k: pytest.fail("enqueued"))
    (backup_dir / NAME).write_bytes(b"x")
    async with session_factory()() as s:
        s.add(User(email="member-backups@x.test", username="member-backups",
                   display_name="M", password_hash=hash_password("hunter2hunter2"),
                   role="member"))
        await s.commit()
    login = await client.post("/api/auth/login", json={
        "email": "member-backups@x.test", "password": "hunter2hunter2"})
    assert login.status_code == 200
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]

    assert (await client.get("/api/admin/backups")).status_code == 403
    assert (await client.post("/api/admin/backups/run")).status_code == 403
    assert (await client.get(f"/api/admin/backups/{NAME}")).status_code == 403
    assert (await client.delete(f"/api/admin/backups/{NAME}")).status_code == 403
    assert (backup_dir / NAME).exists()


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

async def test_backup_settings_defaults_and_round_trip(authed_admin_client, backup_dir):
    c = authed_admin_client
    target = backup_dir / "nested" / "dir"
    r = await c.put("/api/admin/settings", json={
        "backup_enabled": False, "backup_time": "23:59", "backup_keep": 365,
        "backup_dir": str(target),
    })
    assert r.status_code == 200, r.text
    got = (await c.get("/api/admin/settings")).json()
    assert got["backup_enabled"] is False
    assert got["backup_time"] == "23:59"
    assert got["backup_keep"] == 365
    assert got["backup_dir"] == str(target)
    assert target.is_dir()  # created on save

    # Stored normalised (no "..").
    r = await c.put("/api/admin/settings", json={
        "backup_dir": str(backup_dir / "x" / ".." / "nested" / "dir")})
    assert r.status_code == 200, r.text
    assert r.json()["backup_dir"] == str(target)

    # Leaving backup_dir out keeps it; an explicit null clears it.
    r = await c.put("/api/admin/settings", json={"backup_keep": 1})
    assert r.json()["backup_dir"] == str(target)
    r = await c.put("/api/admin/settings", json={"backup_dir": None})
    assert r.status_code == 200, r.text
    assert r.json()["backup_dir"] is None


async def test_backup_settings_validation(authed_admin_client, backup_dir):
    c = authed_admin_client
    before = (await c.get("/api/admin/settings")).json()
    for bad in (
        {"backup_time": "24:00"},
        {"backup_time": "3:30"},
        {"backup_time": "03:60"},
        {"backup_time": "03:30 "},
        {"backup_keep": 0},
        {"backup_keep": 366},
        {"backup_dir": "relative/dir"},
        {"backup_dir": ""},
    ):
        r = await c.put("/api/admin/settings", json=bad)
        assert r.status_code == 422, (bad, r.text)
    # An existing file can't be the backup dir.
    blocker = backup_dir / "a-file"
    blocker.write_text("x")
    r = await c.put("/api/admin/settings", json={"backup_dir": str(blocker)})
    assert r.status_code == 422, r.text
    r = await c.put("/api/admin/settings", json={"backup_dir": str(blocker / "sub")})
    assert r.status_code == 422, r.text
    assert (await c.get("/api/admin/settings")).json() == before

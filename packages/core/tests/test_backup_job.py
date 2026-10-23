"""Scheduled database backups (P2a A5): due logic, the gzipped dump, retention,
the free-space guard, failure status + notification, and the hourly tick.

``pg_dump`` itself is replaced by a small Python subprocess so the real
streaming/exit-code handling runs without the Postgres client tools. Every
backup is written under ``tmp_path``.
"""
from __future__ import annotations

import gzip
import sys
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.db import session_factory
from setvault_core.jobs import backup
from setvault_core.models.engagement_3c import InAppNotification
from setvault_core.models.identity import User
from setvault_core.services import pg_dump
from setvault_core.services.passwords import hash_password
from setvault_core.services.system_config import get_config
from sqlalchemy import delete, select

_FIELDS = (
    "backup_enabled", "backup_time", "backup_keep", "backup_dir",
    "last_backup_at", "last_backup_status", "last_backup_error", "last_backup_bytes",
)


@pytest.fixture
async def cfg_state(tmp_path):
    """Point the backup dir at tmp_path; restore every backup field after."""
    async with session_factory()() as s:
        cfg = await get_config(s)
        saved = {f: getattr(cfg, f) for f in _FIELDS}
        cfg.backup_enabled = True
        cfg.backup_time = "03:30"
        cfg.backup_keep = 14
        cfg.backup_dir = str(tmp_path)
        cfg.last_backup_at = None
        cfg.last_backup_status = None
        cfg.last_backup_error = None
        cfg.last_backup_bytes = None
        await s.commit()
    yield tmp_path
    async with session_factory()() as s:
        cfg = await get_config(s)
        for f, v in saved.items():
            setattr(cfg, f, v)
        await s.commit()


async def _config():
    async with session_factory()() as s:
        return await get_config(s)


async def _set(**fields):
    async with session_factory()() as s:
        cfg = await get_config(s)
        for k, v in fields.items():
            setattr(cfg, k, v)
        await s.commit()


def _fake_pg_dump(monkeypatch, code: str) -> None:
    """Make the dump a Python subprocess running ``code`` (stdout = the dump)."""
    monkeypatch.setattr(pg_dump, "pg_dump_args", lambda url: [sys.executable, "-c", code])


def _touch_backups(directory, *names):
    for n in names:
        (directory / n).write_bytes(b"old")


# --------------------------------------------------------------------------- #
# is_due
# --------------------------------------------------------------------------- #

def _local(h: int, m: int, day: int = 23) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=UTC)


def test_is_due_before_and_after_time():
    assert backup.is_due(_local(3, 29), "03:30", None) is False
    assert backup.is_due(_local(3, 30), "03:30", None) is True
    assert backup.is_due(_local(23, 59), "03:30", None) is True


def test_is_due_false_after_success_today():
    # A second tick the same day doesn't run it again.
    assert backup.is_due(_local(4, 30), "03:30", _local(3, 31)) is False
    assert backup.is_due(_local(23, 0), "03:30", _local(3, 31)) is False


def test_catch_up_later_same_day():
    # The worker was down at 03:30: the first tick that day still runs it.
    yesterday = _local(3, 31, day=22)
    assert backup.is_due(_local(10, 0), "03:30", yesterday) is True


def test_effective_dir_prefers_config_then_env(monkeypatch, tmp_path):
    class Cfg:
        backup_dir = None

    monkeypatch.delenv("SETVAULT_BACKUP_PATH", raising=False)
    assert backup.effective_dir(Cfg()).as_posix() == "/srv/backups"
    monkeypatch.setenv("SETVAULT_BACKUP_PATH", str(tmp_path / "env"))
    assert backup.effective_dir(Cfg()) == tmp_path / "env"
    Cfg.backup_dir = str(tmp_path / "cfg")
    assert backup.effective_dir(Cfg()) == tmp_path / "cfg"


# --------------------------------------------------------------------------- #
# perform_backup
# --------------------------------------------------------------------------- #

async def test_run_writes_gz_and_renames_tmp(cfg_state, monkeypatch):
    # Big enough to arrive in several chunks.
    _fake_pg_dump(monkeypatch, "import sys; sys.stdout.buffer.write(b'SELECT 1;\\n' * 30000)")
    result = await backup.perform_backup()

    assert result["status"] == "ok", result
    assert backup.BACKUP_NAME_RE.fullmatch(result["file"])
    path = cfg_state / result["file"]
    assert path.is_file()
    assert list(cfg_state.glob("*.tmp")) == []
    assert gzip.decompress(path.read_bytes()) == b"SELECT 1;\n" * 30000
    assert result["bytes"] == path.stat().st_size
    assert result["pruned"] == []

    cfg = await _config()
    assert cfg.last_backup_status == "ok"
    assert cfg.last_backup_error is None
    assert cfg.last_backup_bytes == path.stat().st_size
    assert cfg.last_backup_at is not None


async def test_prunes_beyond_keep(cfg_state, monkeypatch):
    _fake_pg_dump(monkeypatch, "import sys; sys.stdout.buffer.write(b'x')")
    _touch_backups(
        cfg_state,
        "setvault-20200101-000000.sql.gz",
        "setvault-20200102-000000.sql.gz",
        "setvault-20200103-000000.sql.gz",
    )
    (cfg_state / "notes.txt").write_text("keep me")
    (cfg_state / "setvault-backup-20200101.tar").write_bytes(b"keep me too")
    await _set(backup_keep=2)

    result = await backup.perform_backup()

    assert result["status"] == "ok", result
    remaining = sorted(p.name for p in cfg_state.glob("setvault-*.sql.gz"))
    assert remaining == ["setvault-20200103-000000.sql.gz", result["file"]]
    assert sorted(result["pruned"]) == [
        "setvault-20200101-000000.sql.gz", "setvault-20200102-000000.sql.gz",
    ]
    assert (cfg_state / "notes.txt").is_file()
    assert (cfg_state / "setvault-backup-20200101.tar").is_file()


@pytest.fixture
async def admin_user():
    async with session_factory()() as s:
        user = User(
            email=f"bk-{uuid.uuid4().hex[:6]}@x.test",
            username=f"bk{uuid.uuid4().hex[:6]}",
            display_name="Backup admin",
            password_hash=hash_password("aaaaaaaa"),
            role="admin",
        )
        s.add(user)
        await s.commit()
    yield user
    async with session_factory()() as s:
        await s.execute(delete(InAppNotification).where(InAppNotification.user_id == user.id))
        await s.execute(delete(User).where(User.id == user.id))
        await s.commit()


async def _backup_notifications(user_id):
    async with session_factory()() as s:
        return (await s.execute(select(InAppNotification.payload).where(
            InAppNotification.user_id == user_id,
            InAppNotification.kind == "maintenance",
        ))).scalars().all()


async def test_low_space_fails_and_notifies(cfg_state, monkeypatch, admin_user):
    from collections import namedtuple

    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda p: Usage(10**9, 0, 1500))
    called = []
    monkeypatch.setattr(pg_dump, "pg_dump_args", lambda url: called.append(url) or [])
    await _set(last_backup_bytes=1000)

    result = await backup.perform_backup()

    assert result["status"] == "failed"
    assert result["error"].startswith("not enough free space (need ~")
    assert called == []  # refused before dumping
    assert list(cfg_state.iterdir()) == []
    cfg = await _config()
    assert cfg.last_backup_status == "failed"
    assert cfg.last_backup_error == result["error"]
    assert cfg.last_backup_bytes == 1000  # the guard's reference is kept
    assert await _backup_notifications(admin_user.id) == [
        {"event": "backup.failed", "error": result["error"]},
    ]


async def test_pg_dump_failure_sets_failed_status(cfg_state, monkeypatch, admin_user):
    _fake_pg_dump(
        monkeypatch,
        "import sys; sys.stdout.buffer.write(b'partial'); "
        "sys.stderr.write('connection refused'); sys.exit(3)",
    )
    result = await backup.perform_backup()

    assert result["status"] == "failed"
    assert "pg_dump exited 3" in result["error"]
    assert "connection refused" in result["error"]
    assert list(cfg_state.iterdir()) == []  # no .tmp, no half file
    cfg = await _config()
    assert cfg.last_backup_status == "failed"
    assert cfg.last_backup_error == result["error"]
    payloads = await _backup_notifications(admin_user.id)
    assert payloads == [{"event": "backup.failed", "error": result["error"]}]


async def test_disabled_backup_runs_only_when_forced(cfg_state, monkeypatch):
    _fake_pg_dump(monkeypatch, "import sys; sys.stdout.buffer.write(b'x')")
    await _set(backup_enabled=False)
    assert (await backup.perform_backup())["status"] == "skipped"
    assert list(cfg_state.iterdir()) == []
    assert (await backup.perform_backup(force=True))["status"] == "ok"


# --------------------------------------------------------------------------- #
# backup_tick
# --------------------------------------------------------------------------- #

def _freeze(monkeypatch, now: datetime):
    """Freeze ``datetime.now()`` in the job module at a local wall time."""
    real = backup.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(backup, "datetime", Frozen)


async def test_tick_skips_when_disabled(cfg_state, monkeypatch):
    ran = []

    async def fake_perform(force=False):
        ran.append(force)
        return {"status": "ok"}

    monkeypatch.setattr(backup, "perform_backup", fake_perform)
    _freeze(monkeypatch, datetime.now().astimezone().replace(hour=12, minute=0))
    await _set(backup_enabled=False)
    assert await backup.backup_tick() is None
    assert ran == []


async def test_tick_runs_when_due_and_not_again_after_success(cfg_state, monkeypatch):
    ran = []

    async def fake_perform(force=False):
        ran.append(force)
        return {"status": "ok"}

    monkeypatch.setattr(backup, "perform_backup", fake_perform)
    now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    _freeze(monkeypatch, now)

    # Last success yesterday: catch-up run.
    await _set(last_backup_at=(now - timedelta(days=1)).astimezone(UTC),
               last_backup_status="ok")
    assert await backup.backup_tick() == {"status": "ok"}
    # Succeeded earlier today: nothing to do.
    await _set(last_backup_at=(now - timedelta(hours=1)).astimezone(UTC),
               last_backup_status="ok")
    assert await backup.backup_tick() is None
    # Today's run failed: the next tick retries.
    await _set(last_backup_status="failed")
    assert await backup.backup_tick() == {"status": "ok"}
    assert ran == [False, False]

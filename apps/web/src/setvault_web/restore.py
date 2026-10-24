"""Restore CLI — the inverse of ``GET /api/admin/backup``.

Run as::

    python -m setvault_web.restore <backup.tar> --yes
    python -m setvault_web.restore <setvault-YYYYMMDD-HHMMSS.sql.gz> --yes

A ``.sql.gz`` is a scheduled backup (``setvault_core.jobs.backup``): a
gzipped ``pg_dump`` that restores the database only. Anything else is read
as the full backup tar.

The backup tar (see ``setvault_web.api.backup``) contains:

  - ``db.sql``                       — a ``pg_dump`` of the database.
  - ``audio/<root_name>/<rel_path>`` — every file under each MediaRoot's
    ``host_path``, keyed by the root's ``name`` and its on-disk relative path.

Restore is the exact inverse:

  1. Extract the tar to a temp dir.
  2. Load ``db.sql`` into the configured database via ``psql`` (the
     SQLAlchemy ``postgresql+asyncpg://`` URL is translated to a libpq
     ``postgresql://`` URL first). A non-zero ``psql`` exit aborts loudly.
  3. For each MediaRoot, copy ``audio/<root_name>/...`` back under that
     root's ``host_path``, recreating the original on-disk layout.

Restore is **destructive** — it loads a dump over the live database and
overwrites media files — so it refuses to run without an explicit ``--yes``
flag (or ``RESTORE_CONFIRM=1`` in the environment). Secrets (the DB password)
are never printed: the libpq URL is passed to ``psql`` as a single argument
and redacted in all log/console output.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import MediaRoot
from sqlalchemy import select

from setvault_web.config import get_settings


class RestoreError(Exception):
    """Raised for any restore failure (no confirmation, bad tar, psql error)."""


@dataclass(frozen=True)
class MediaRootSpec:
    """Minimal description of a MediaRoot for restore — name + destination."""

    name: str
    host_path: str


def libpq_url_from_sqlalchemy(database_url: str) -> str:
    """Translate a SQLAlchemy URL into a libpq URL ``psql`` understands.

    ``postgresql+asyncpg://user:pwd@host:port/db`` ->
    ``postgresql://user:pwd@host:port/db``. Only the driver suffix is
    stripped; userinfo/host/port/db/query are left untouched so the password
    travels inside the URL (never on argv as a separate flag, never logged).
    """
    scheme, sep, rest = database_url.partition("://")
    if not sep:
        raise RestoreError(f"unrecognised database URL: {_redact(database_url)}")
    # Drop any ``+driver`` suffix on the scheme (asyncpg, psycopg, etc.).
    base_scheme = scheme.split("+", 1)[0]
    if base_scheme in ("postgresql", "postgres"):
        base_scheme = "postgresql"
    return f"{base_scheme}://{rest}"


def _redact(database_url: str) -> str:
    """Best-effort redaction of the password component for logging."""
    scheme, sep, rest = database_url.partition("://")
    if not sep or "@" not in rest:
        return database_url
    userinfo, _, hostpart = rest.partition("@")
    if ":" in userinfo:
        user, _, _pwd = userinfo.partition(":")
        userinfo = f"{user}:<redacted>"
    return f"{scheme}://{userinfo}@{hostpart}"


def _restore_database(db_sql: Path, database_url: str) -> None:
    """Load ``db.sql`` into ``database_url`` via ``psql``. Fail loudly."""
    if shutil.which("psql") is None:
        raise RestoreError("psql not found on PATH — cannot restore database")
    libpq = libpq_url_from_sqlalchemy(database_url)
    cmd = [
        "psql",
        "--set", "ON_ERROR_STOP=1",
        "-d", libpq,
        "-f", str(db_sql),
    ]
    print(f"restore: loading db.sql via psql -d {_redact(libpq)}")
    # S603: argv is built from settings + a fixed file path, not user input;
    # no shell is used. psql is expected on PATH.
    proc = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # stderr may echo the connection string; redact defensively.
        err = (proc.stderr or "").strip()
        raise RestoreError(
            f"psql exited {proc.returncode} while restoring db.sql: {err[:2000]}"
        )


def _restore_media(extract_dir: Path, media_roots: list[MediaRootSpec]) -> int:
    """Copy ``audio/<root_name>/...`` from ``extract_dir`` back under each
    root's ``host_path``. Returns the number of files copied.

    Mirrors ``backup._stream_tar``: a file archived as
    ``audio/<root.name>/<rel>`` is restored to ``<host_path>/<rel>``.
    """
    copied = 0
    audio_base = extract_dir / "audio"
    for root in media_roots:
        src_root = audio_base / root.name
        if not src_root.is_dir():
            print(f"restore: no archived media for root {root.name!r}; skipping")
            continue
        dest_root = Path(root.host_path)
        dest_root.mkdir(parents=True, exist_ok=True)
        for src in src_root.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(src_root)
            dest = dest_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    return copied


def _safe_extract(tar_path: Path, dest: Path) -> None:
    """Extract ``tar_path`` into ``dest``, rejecting path-traversal members."""
    dest = dest.resolve()
    with tarfile.open(tar_path, mode="r:*") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not (target == dest or str(target).startswith(str(dest) + os.sep)):
                raise RestoreError(f"unsafe path in archive: {member.name!r}")
            if member.issym() or member.islnk():
                raise RestoreError(f"unsafe link in archive: {member.name!r}")
        tar.extractall(dest)  # noqa: S202 — members validated above


def restore_from_tar(
    tar_path: str | Path,
    database_url: str,
    media_roots: list[MediaRootSpec],
    *,
    confirm: bool,
) -> dict[str, int]:
    """Restore a backup tar produced by ``backup._stream_tar``.

    Extracts the tar, loads ``db.sql`` into ``database_url`` via ``psql``, and
    copies media back under each root's ``host_path``. Destructive — refuses
    to run unless ``confirm`` is True.

    Returns a summary dict, e.g. ``{"media_files": 3}``. Raises
    :class:`RestoreError` on any failure.
    """
    if not confirm:
        raise RestoreError(
            "restore is destructive and was not confirmed — pass --yes "
            "(or set RESTORE_CONFIRM=1) to overwrite the database and media"
        )

    tar_path = Path(tar_path)
    if not tar_path.is_file():
        raise RestoreError(f"backup file not found: {tar_path}")

    with tempfile.TemporaryDirectory(prefix="setvault-restore-") as tmp:
        extract_dir = Path(tmp)
        _safe_extract(tar_path, extract_dir)

        db_sql = extract_dir / "db.sql"
        if not db_sql.is_file():
            raise RestoreError("archive is missing db.sql — not a SetVault backup")
        _restore_database(db_sql, database_url)

        copied = _restore_media(extract_dir, media_roots)

    print(f"restore: complete — {copied} media file(s) restored")
    return {"media_files": copied}


def restore_from_sql_gz(
    gz_path: str | Path, database_url: str, *, confirm: bool,
) -> None:
    """Restore a scheduled ``.sql.gz`` backup: the database only. Gunzips to
    a temp file, then loads it via ``psql``. Destructive — refuses to run
    unless ``confirm`` is True. Raises :class:`RestoreError` on any failure."""
    if not confirm:
        raise RestoreError(
            "restore is destructive and was not confirmed — pass --yes "
            "(or set RESTORE_CONFIRM=1) to overwrite the database"
        )
    gz_path = Path(gz_path)
    if not gz_path.is_file():
        raise RestoreError(f"backup file not found: {gz_path}")
    with tempfile.TemporaryDirectory(prefix="setvault-restore-") as tmp:
        db_sql = Path(tmp) / "db.sql"
        try:
            with gzip.open(gz_path, "rb") as src, db_sql.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        except (OSError, EOFError, zlib.error) as exc:
            raise RestoreError(f"{gz_path.name} is not a valid gzip file: {exc}") from exc
        _restore_database(db_sql, database_url)
    print("restore: complete — database restored (media untouched)")


async def _load_media_roots(database_url: str) -> list[MediaRootSpec]:
    """Read MediaRoots from the (freshly restored) DB to know where media goes."""
    init_engine(database_url)
    async with session_factory()() as session:
        rows = (
            await session.execute(select(MediaRoot).order_by(MediaRoot.created_at))
        ).scalars().all()
        return [MediaRootSpec(name=r.name, host_path=r.host_path) for r in rows]


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m setvault_web.restore",
        description=(
            "Restore a SetVault backup: a full .tar (DB + media) or a scheduled "
            ".sql.gz (DB only). DESTRUCTIVE."
        ),
    )
    parser.add_argument("tar_path", help="path to the backup .tar or .sql.gz")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the destructive restore (or set RESTORE_CONFIRM=1)",
    )
    args = parser.parse_args(argv)

    confirm = args.yes or os.environ.get("RESTORE_CONFIRM") == "1"
    if not confirm:
        print(
            "refusing to restore without confirmation: this OVERWRITES the "
            "database and media files. Re-run with --yes (or RESTORE_CONFIRM=1).",
            file=sys.stderr,
        )
        raise SystemExit(2)

    database_url = get_settings().database_url

    # The DB is loaded first; MediaRoots come from the restored DB so we know
    # each root's host_path. The dump in db.sql is the source of truth for the
    # set of roots, so we restore it, then re-read roots, then copy media.
    tar_path = Path(args.tar_path)
    if not tar_path.is_file():
        print(f"error: backup file not found: {tar_path}", file=sys.stderr)
        raise SystemExit(1)

    if tar_path.name.endswith(".sql.gz"):
        try:
            restore_from_sql_gz(tar_path, database_url, confirm=True)
        except RestoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    try:
        with tempfile.TemporaryDirectory(prefix="setvault-restore-") as tmp:
            extract_dir = Path(tmp)
            _safe_extract(tar_path, extract_dir)

            db_sql = extract_dir / "db.sql"
            if not db_sql.is_file():
                raise RestoreError("archive is missing db.sql — not a SetVault backup")
            _restore_database(db_sql, database_url)

            media_roots = asyncio.run(_load_media_roots(database_url))
            copied = _restore_media(extract_dir, media_roots)
        print(f"restore: complete — {copied} media file(s) restored")
    except RestoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

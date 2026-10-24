"""``pg_dump`` of the configured database, streamed from its stdout.

Shared by the on-demand admin download (``setvault_web.api.backup``) and the
scheduled backup job (``setvault_core.jobs.backup``).
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import tempfile
from collections.abc import Iterator

logger = logging.getLogger(__name__)

_CHUNK = 64 * 1024


class PgDumpError(RuntimeError):
    """pg_dump exited non-zero."""


def pg_dump_args(database_url: str) -> list[str]:
    """Convert ``postgresql+asyncpg://user:pwd@host:port/db`` into the
    arg list pg_dump expects. Drops the +asyncpg driver suffix and uses
    ``-d <full-url>`` so passwords don't end up on the command line.
    """
    plain = database_url.replace("+asyncpg", "")
    # --clean --if-exists makes the dump drop-then-recreate each object, so a
    # restore works whether the target DB is empty OR already has the migrated
    # schema (the bundled-mode reality: the embedded PG auto-migrates on boot).
    # Without it, restore fails on "<object> already exists".
    return [
        "pg_dump", "--no-owner", "--no-privileges", "--clean", "--if-exists",
        "-d", plain,
    ]


def stream_pg_dump(database_url: str, *, check: bool = False) -> Iterator[bytes]:
    """Yield pg_dump's stdout in chunks.

    A non-zero exit is logged; with ``check`` it also raises
    :class:`PgDumpError` (carrying pg_dump's stderr) once the output has been
    read to the end.
    """
    cmd = pg_dump_args(database_url)
    logger.info("backup: invoking %s", shlex.join(cmd[:-1]) + " <redacted>")
    # stderr goes to a file, not a pipe: a chatty pg_dump can't fill a pipe
    # nobody reads while we drain stdout.
    with tempfile.TemporaryFile() as err_fp:
        # S603: cmd is constructed from settings, not user input. pg_dump is
        # on PATH inside the image.
        proc = subprocess.Popen(  # noqa: S603
            cmd, stdout=subprocess.PIPE, stderr=err_fp, bufsize=0,
        )
        finished = False
        try:
            assert proc.stdout is not None
            while chunk := proc.stdout.read(_CHUNK):
                yield chunk
            finished = True
        finally:
            if proc.stdout:
                proc.stdout.close()
            proc.wait(timeout=30)
            if proc.returncode != 0:
                err_fp.seek(0)
                err = err_fp.read(4000).decode("utf-8", errors="replace").strip()
                logger.warning("backup: pg_dump exited %s: %s", proc.returncode, err[:1000])
                if check and finished:
                    raise PgDumpError(f"pg_dump exited {proc.returncode}: {err[:1000]}")

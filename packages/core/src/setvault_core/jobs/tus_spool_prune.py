"""Scheduled daily job: prune abandoned uploads from tusd's spool.

Finished uploads are removed by the post-finish hook once their bytes are in a
MediaRoot. Uploads the browser never finished (tab closed, network gone) stay
as ``<id>`` + ``<id>.info`` pairs under ``<SETVAULT_CACHE_PATH>/tus`` forever;
anything untouched for ``MAX_AGE`` is deleted. tusd can still resume an upload
younger than that.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def spool_dir() -> Path:
    return Path(os.environ.get("SETVAULT_CACHE_PATH", "/srv/cache")) / "tus"


def prune_tus_spool(
    directory: Path | None = None, *, max_age: float = MAX_AGE_SECONDS, now: float | None = None,
) -> dict:
    """Delete spool files whose mtime is older than ``max_age``. Returns
    ``{"removed": N, "errors": N}``. A missing spool dir is not an error."""
    directory = directory or spool_dir()
    now = time.time() if now is None else now
    summary = {"removed": 0, "errors": 0}
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return summary
    for entry in entries:
        try:
            if not entry.is_file() or now - entry.stat().st_mtime < max_age:
                continue
            entry.unlink()
            summary["removed"] += 1
        except OSError as exc:
            logger.warning("tus spool prune: failed on %s: %s", entry, exc)
            summary["errors"] += 1
    return summary


def run_prune_tus_spool() -> dict:
    """RQ entry point (scheduled)."""
    return prune_tus_spool()

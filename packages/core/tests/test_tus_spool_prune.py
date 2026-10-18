from __future__ import annotations

import os
from pathlib import Path

from setvault_core.jobs.tus_spool_prune import MAX_AGE_SECONDS, prune_tus_spool


def _touch(path: Path, mtime: float) -> None:
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))


def test_prunes_abandoned_uploads_and_keeps_resumable_ones(tmp_path: Path):
    now = 10 * MAX_AGE_SECONDS
    _touch(tmp_path / "old", now - MAX_AGE_SECONDS - 1)
    _touch(tmp_path / "old.info", now - MAX_AGE_SECONDS - 1)
    _touch(tmp_path / "fresh", now - 60)
    _touch(tmp_path / "fresh.info", now - 60)

    summary = prune_tus_spool(tmp_path, now=now)

    assert summary == {"removed": 2, "errors": 0}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fresh", "fresh.info"]


def test_missing_spool_dir_is_not_an_error(tmp_path: Path):
    assert prune_tus_spool(tmp_path / "nope") == {"removed": 0, "errors": 0}

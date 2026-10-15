import asyncio
import os
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.pipeline import run_pipeline
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User


async def _make_set(tmp_path: Path) -> uuid.UUID:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="missing.flac", uploaded_by=u.id, source_type="upload",
                       status="processing")
        s.add(live)
        await s.commit()
        return live.id


async def _status(sid: uuid.UUID) -> str:
    async with session_factory()() as s:
        return (await s.get(LiveSet, sid)).status


def test_failed_pipeline_marks_set_failed(tmp_path: Path, monkeypatch):
    """A failing step must flip the set to ``failed`` instead of leaving it
    stuck in ``processing``. Runs with the worker's real pooled engine: the
    pipeline and the failure handler use separate ``asyncio.run`` loops, and a
    pooled asyncpg connection from the first loop can't be reused in the second.
    """
    url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    sid = asyncio.run(_make_set(tmp_path))

    monkeypatch.delenv("SETVAULT_DB_NULLPOOL")
    monkeypatch.setenv("DATABASE_URL", url)
    # The source file doesn't exist, so the first step (probe) fails.
    with pytest.raises(Exception):  # noqa: B017
        run_pipeline(str(sid))

    monkeypatch.setenv("SETVAULT_DB_NULLPOOL", "1")
    init_engine(url)
    assert asyncio.run(_status(sid)) == "failed"

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.loudness_backfill import remeasure_bogus_loudness
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def _seed(tmp_path: Path, sets: list[tuple[str, float | None]]) -> dict[str, uuid.UUID]:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = {}
        for audio_path, lufs in sets:
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                           audio_path=audio_path, uploaded_by=u.id, source_type="upload",
                           status="published", normalized_lufs=lufs)
            s.add(live)
            await s.flush()
            ids[audio_path] = live.id
        await s.commit()
        return ids


async def _lufs(sid: uuid.UUID) -> float | None:
    async with session_factory()() as s:
        return (await s.get(LiveSet, sid)).normalized_lufs


async def test_backfill_remeasures_only_bogus_values(tmp_path: Path, require_tools):
    require_tools("ffmpeg")
    for name in ("bogus.flac", "good.flac"):
        subprocess.run(  # noqa: ASYNC221, S603
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",  # noqa: S607
             str(tmp_path / name)],
            check=True, capture_output=True,
        )
    ids = await _seed(tmp_path, [
        ("bogus.flac", -70.0),
        ("good.flac", -14.5),
        ("gone.flac", -70.0),  # original missing: counted as failed, not fatal
    ])

    result = await remeasure_bogus_loudness()

    assert result == {"candidates": 2, "remeasured": 1, "failed": 1}
    assert -40 < await _lufs(ids["bogus.flac"]) < 0
    assert await _lufs(ids["good.flac"]) == -14.5
    assert await _lufs(ids["gone.flac"]) == -70.0

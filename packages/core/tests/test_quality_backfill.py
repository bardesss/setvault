import array
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import quality_backfill as qb
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.identity import User
from setvault_core.services.audio_match import MATCHER_VERSION
from setvault_core.services.audio_quality import AudioQuality
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def _seed(tmp_path: Path, names: list[str]) -> dict[str, uuid.UUID]:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = {}
        for n in names:
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                           audio_path=n, uploaded_by=u.id, source_type="upload",
                           status="published")
            s.add(live)
            await s.flush()
            ids[n] = live.id
        await s.commit()
        return ids


def _tone(path: Path) -> None:
    subprocess.run(  # noqa: S603
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",  # noqa: S607
         str(path)],
        check=True, capture_output=True,
    )


async def test_backfill_fills_missing_fingerprint_and_quality(tmp_path: Path, require_tools):
    require_tools("ffmpeg", "ffprobe", "fpcalc")
    _tone(tmp_path / "a.flac")
    ids = await _seed(tmp_path, ["a.flac"])

    async with session_factory()() as s:
        before = await qb.backfill_candidates(s)
    assert before == {"to_fingerprint": 1, "to_measure": 1}

    res = await qb.run_backfill_batch()
    assert res["processed"] == 1 and res["errors"] == 0 and res["remaining"] == 0

    async with session_factory()() as s:
        live = await s.get(LiveSet, ids["a.flac"])
        assert live.quality_tier is not None
        assert live.quality_measured_at is not None
        assert live.status == "published"
        assert live.duplicate_of is None
        fps = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == live.id)
        )).scalars().all()
        assert len(fps) == 1
        assert fps[0].raw and fps[0].raw_version == MATCHER_VERSION


async def test_backfill_skips_already_done(tmp_path: Path, monkeypatch):
    ids = await _seed(tmp_path, ["done.flac"])
    async with session_factory()() as s:
        live = await s.get(LiveSet, ids["done.flac"])
        live.quality_measured_at = datetime.now(UTC)
        s.add(SetFingerprint(live_set_id=live.id, fingerprint_hash="h", duration_seconds=1.0,
                             raw=b"\x01\x00\x00\x00", raw_version=MATCHER_VERSION))
        await s.commit()

    def boom(*_a, **_k):
        raise AssertionError("must not recompute")
    monkeypatch.setattr(qb, "compute_raw_fingerprint", boom)
    monkeypatch.setattr(qb, "measure_quality", boom)

    async with session_factory()() as s:
        assert await qb.backfill_candidates(s) == {"to_fingerprint": 0, "to_measure": 0}
    res = await qb.run_backfill_batch()
    assert (res["processed"], res["errors"], res["remaining"]) == (0, 0, 0)


async def test_backfill_continues_after_one_bad_file(tmp_path: Path, monkeypatch):
    (tmp_path / "ok.flac").write_bytes(b"x")
    ids = await _seed(tmp_path, ["gone.flac", "ok.flac"])  # gone.flac has no file
    monkeypatch.setattr(
        qb, "compute_raw_fingerprint",
        lambda _p: (array.array("I", [1, 2, 3]), 3.0),
    )
    monkeypatch.setattr(
        qb, "measure_quality",
        lambda _p: AudioQuality("flac", None, 44100, 16, True, "lossless"),
    )

    res = await qb.run_backfill_batch()
    assert res["processed"] == 1 and res["errors"] == 1
    assert res["error_ids"] == [ids["gone.flac"]]

    async with session_factory()() as s:
        ok = await s.get(LiveSet, ids["ok.flac"])
        assert ok.quality_tier == "lossless"
        gone = await s.get(LiveSet, ids["gone.flac"])
        assert gone.quality_measured_at is None

    # The full run terminates despite the permanently bad file.
    totals = await qb._run_quality_backfill()
    assert totals["processed"] == 0 and totals["errors"] == 1

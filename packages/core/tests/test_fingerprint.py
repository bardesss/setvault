import importlib.util
import json
import os
import random
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.fingerprint import fingerprint_audio
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.identity import User
from setvault_core.services.audio_match import MATCHER_VERSION, raw_from_bytes
from sqlalchemy import select

# pytest runs with --import-mode=importlib, so sibling modules aren't on sys.path.
_spec = importlib.util.spec_from_file_location(
    "fixtures_audio", Path(__file__).with_name("fixtures_audio.py"))
fixtures_audio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures_audio)


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
def fpcalc_present(require_tools):
    require_tools("fpcalc")


async def test_fingerprint_stores_hash(tmp_path: Path, fpcalc_present, require_tools):
    require_tools("ffmpeg")
    audio = tmp_path / "audio.flac"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-t", "3", str(audio)]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: ASYNC221, S603
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="audio.flac", uploaded_by=u.id, source_type="upload",
                       status="processing", duration_seconds=3)
        s.add(live)
        await s.commit()
        sid = live.id

    await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        rows = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == sid),
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].fingerprint_hash


async def _make_set(tmp_path: Path) -> uuid.UUID:
    (tmp_path / "audio.flac").write_bytes(b"not really flac")
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="audio.flac", uploaded_by=u.id, source_type="upload",
                       status="processing", duration_seconds=3)
        s.add(live)
        await s.commit()
        return live.id


def _fake_fpcalc(monkeypatch, returncode: int, stdout: str) -> None:
    def fake_run(args, check=False, **_kwargs):
        proc = subprocess.CompletedProcess(
            args, returncode, stdout=stdout,
            stderr="ERROR: Error decoding audio frame (End of file)\n",
        )
        if check:
            proc.check_returncode()
        return proc
    monkeypatch.setattr("setvault_core.services.audio_match.subprocess.run", fake_run)


def _items_json(items: list[int], duration: float = 3.0) -> str:
    return json.dumps({"duration": duration, "fingerprint": items}) + "\n"


def _random_items(seed: int, n: int = 2000) -> list[int]:
    rng = random.Random(seed)  # noqa: S311
    return [rng.getrandbits(32) for _ in range(n)]


async def test_fingerprint_accepts_fpcalc_eof_exit_code(tmp_path: Path, monkeypatch):
    """chromaprint 1.5.1 (Debian bookworm, Ubuntu noble) exits 3 at end of file
    even though it printed a valid fingerprint. That must not fail ingest."""
    sid = await _make_set(tmp_path)
    _fake_fpcalc(monkeypatch, 3, _items_json([1, 2, 3]))

    await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        rows = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == sid),
        )).scalars().all()
        assert len(rows) == 1


async def test_fingerprint_raises_when_fpcalc_prints_nothing(tmp_path: Path, monkeypatch):
    sid = await _make_set(tmp_path)
    _fake_fpcalc(monkeypatch, 3, "")

    with pytest.raises(RuntimeError, match="fpcalc failed"):
        await fingerprint_audio(str(sid))


async def test_third_copy_of_a_set_is_flagged_not_crashed(tmp_path: Path, monkeypatch):
    """Duplicates record their own fingerprint row, so by the third copy the
    hash matches several rows. That must flag the copy, not raise
    MultipleResultsFound, and must point at the earliest (original) set."""
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(5)))
    original = await _make_set(tmp_path)
    second = await _make_set(tmp_path)
    third = await _make_set(tmp_path)

    for sid in (original, second, third):
        await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, original)).duplicate_of is None
        assert (await s.get(LiveSet, second)).duplicate_of == original
        assert (await s.get(LiveSet, third)).duplicate_of == original


async def test_fingerprint_rerun_does_not_add_a_second_row(tmp_path: Path, monkeypatch):
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(6)))
    sid = await _make_set(tmp_path)

    await fingerprint_audio(str(sid))
    await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        rows = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == sid),
        )).scalars().all()
        assert len(rows) == 1
        assert (await s.get(LiveSet, sid)).duplicate_of is None


async def test_rerun_refreshes_raw_and_keeps_duplicate_link(tmp_path: Path, monkeypatch):
    items = _random_items(7)
    _fake_fpcalc(monkeypatch, 0, _items_json(items))
    original = await _make_set(tmp_path)
    dup = await _make_set(tmp_path)
    await fingerprint_audio(str(original))
    await fingerprint_audio(str(dup))

    _fake_fpcalc(monkeypatch, 0, _items_json(items[:1500]))  # same audio, shorter decode
    await fingerprint_audio(str(dup))

    async with session_factory()() as s:
        rows = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == dup),
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].raw_version == MATCHER_VERSION
        assert len(raw_from_bytes(rows[0].raw)) == 1500
        assert (await s.get(LiveSet, dup)).duplicate_of == original


async def test_match_prefers_original_over_kept_duplicate(tmp_path: Path, monkeypatch):
    """O is the original, K a kept duplicate of O; a new arrival points at O."""
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(11)))
    o = await _make_set(tmp_path)
    k = await _make_set(tmp_path)
    arrival = await _make_set(tmp_path)
    for sid in (o, k, arrival):
        await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, k)).duplicate_of == o
        live = await s.get(LiveSet, arrival)
        assert live.duplicate_of == o
        assert live.match_offset_seconds == pytest.approx(0, abs=0.2)


async def test_unrelated_sets_are_not_flagged(tmp_path: Path, monkeypatch):
    first = await _make_set(tmp_path)
    second = await _make_set(tmp_path)
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(21)))
    await fingerprint_audio(str(first))
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(22)))
    await fingerprint_audio(str(second))

    async with session_factory()() as s:
        live = await s.get(LiveSet, second)
        assert live.duplicate_of is None
        assert live.match_offset_seconds is None


async def test_reencoded_upload_is_flagged_duplicate(tmp_path: Path):
    """Real audio: A as FLAC, then A as MP3 128 (not byte-identical)."""
    fixtures_audio.ensure_tools("ffmpeg", "fpcalc")
    fixtures_audio.build_sets(tmp_path)
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = []
        for name in ("a.flac", "a_mp3_128.mp3"):
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title=name, media_root_id=r.id,
                           audio_path=name, uploaded_by=u.id, source_type="upload",
                           status="processing", duration_seconds=300)
            s.add(live)
            await s.commit()  # distinct created_at, original first
            ids.append(live.id)

    for sid in ids:
        await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, ids[0])).duplicate_of is None
        second = await s.get(LiveSet, ids[1])
        assert second.duplicate_of == ids[0]
        assert abs(second.match_offset_seconds) < 1


async def _set_quality(sid: uuid.UUID, tier: str, lossless: bool, *, deleted: bool = False):
    async with session_factory()() as s:
        live = await s.get(LiveSet, sid)
        live.quality_tier = tier
        live.audio_lossless = lossless
        if deleted:
            live.deleted_at = datetime.now(UTC)
            live.purge_after_at = live.deleted_at + timedelta(days=14)
        await s.commit()


async def test_better_arrival_is_kept_when_original_is_recycled(tmp_path: Path, monkeypatch):
    """A FLAC arriving for a recycled MP3 128 must not be thrown away (R11)."""
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(31)))
    original = await _make_set(tmp_path)
    arrival = await _make_set(tmp_path)
    await fingerprint_audio(str(original))
    await _set_quality(original, "ok", False, deleted=True)
    await _set_quality(arrival, "lossless", True)

    await fingerprint_audio(str(arrival))

    async with session_factory()() as s:
        kept = await s.get(LiveSet, arrival)
        assert kept.deleted_at is None
        assert kept.duplicate_of is None
        assert kept.match_offset_seconds is None
        assert kept.status == "processing"
        assert (await s.get(LiveSet, original)).deleted_at is not None


async def test_unknown_tier_arrival_is_kept_when_original_is_recycled(
    tmp_path: Path, monkeypatch,
):
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(32)))
    original = await _make_set(tmp_path)
    arrival = await _make_set(tmp_path)
    await fingerprint_audio(str(original))
    await _set_quality(original, "lossless", True, deleted=True)

    await fingerprint_audio(str(arrival))  # arrival was never measured

    async with session_factory()() as s:
        kept = await s.get(LiveSet, arrival)
        assert kept.deleted_at is None and kept.duplicate_of is None
        assert (await s.get(LiveSet, original)).deleted_at is not None


async def test_worse_arrival_restores_recycled_original(tmp_path: Path, monkeypatch):
    """MP3 128 arriving for a recycled FLAC: undelete the FLAC, recycle the
    arrival with the normal 14-day window."""
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(33)))
    original = await _make_set(tmp_path)
    arrival = await _make_set(tmp_path)
    await fingerprint_audio(str(original))
    await _set_quality(original, "lossless", True, deleted=True)
    await _set_quality(arrival, "ok", False)

    await fingerprint_audio(str(arrival))

    async with session_factory()() as s:
        restored = await s.get(LiveSet, original)
        assert restored.deleted_at is None and restored.purge_after_at is None
        gone = await s.get(LiveSet, arrival)
        assert gone.duplicate_of == original
        assert gone.deleted_at is not None
        assert gone.purge_after_at - gone.deleted_at == timedelta(days=14)

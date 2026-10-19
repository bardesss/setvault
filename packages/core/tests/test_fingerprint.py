import hashlib
import importlib.util
import json
import os
import random
import shutil
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


def _legacy_stdout(raw_stdout: str) -> str:
    """What plain ``fpcalc -json`` (no -raw) prints for the same fake audio:
    the fingerprint as a compressed base64 string, not a list of items."""
    if not raw_stdout:
        return raw_stdout
    data = json.loads(raw_stdout)
    fp = "AQAA" + hashlib.sha1(json.dumps(data["fingerprint"]).encode()).hexdigest()  # noqa: S324
    return json.dumps({"duration": data["duration"], "fingerprint": fp}) + "\n"


def _legacy_digest(raw_stdout: str) -> str:
    """The pre-7D ``fingerprint_hash``: sha256 of the fpcalc -json string."""
    return hashlib.sha256(
        json.loads(_legacy_stdout(raw_stdout))["fingerprint"].encode("ascii"),
    ).hexdigest()


def _fake_fpcalc(monkeypatch, returncode: int, stdout: str) -> None:
    def fake_run(args, check=False, **_kwargs):
        proc = subprocess.CompletedProcess(
            args, returncode, stdout=stdout if "-raw" in args else _legacy_stdout(stdout),
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


async def _add_legacy_row(sid: uuid.UUID, digest: str, duration: float) -> None:
    """A pre-7D fingerprint row: legacy hash only, no raw."""
    async with session_factory()() as s:
        s.add(SetFingerprint(live_set_id=sid, fingerprint_hash=digest,
                             duration_seconds=duration))
        await s.commit()


async def test_legacy_hash_only_row_still_catches_identical_arrival(
    tmp_path: Path, monkeypatch,
):
    """Rows from before 7D have no raw; until the backfill runs they must still
    match an identical arrival by the old exact hash (R13)."""
    stdout = _items_json(_random_items(41))
    _fake_fpcalc(monkeypatch, 0, stdout)
    original = await _make_set(tmp_path)
    await _add_legacy_row(original, _legacy_digest(stdout), 3.0)
    arrival = await _make_set(tmp_path)

    await fingerprint_audio(str(arrival))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, arrival)).duplicate_of == original
        row = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == arrival),
        )).scalars().one()
        # New rows keep the legacy digest so exact matching keeps working.
        assert row.fingerprint_hash == _legacy_digest(stdout)
        assert row.raw is not None


async def test_legacy_hash_only_row_needs_close_duration(tmp_path: Path, monkeypatch):
    stdout = _items_json(_random_items(42))
    _fake_fpcalc(monkeypatch, 0, stdout)
    original = await _make_set(tmp_path)
    await _add_legacy_row(original, _legacy_digest(stdout), 10.0)  # 7 s off
    arrival = await _make_set(tmp_path)

    await fingerprint_audio(str(arrival))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, arrival)).duplicate_of is None


async def test_real_legacy_row_matches_identical_upload(tmp_path: Path):
    """Real fpcalc: the old code's digest on a raw-less row + the same file again."""
    fixtures_audio.ensure_tools("ffmpeg", "fpcalc")
    fixtures_audio.build_sets(tmp_path)
    shutil.copy(tmp_path / "a.flac", tmp_path / "a_again.flac")
    # Exactly what jobs/fingerprint.py computed before 7D.
    out = subprocess.run(  # noqa: ASYNC221, S603
        ["fpcalc", "-json", str(tmp_path / "a.flac")],  # noqa: S607
        capture_output=True, text=True,
    )
    data = json.loads(out.stdout)
    legacy = hashlib.sha256(data["fingerprint"].encode("ascii")).hexdigest()
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = []
        for name in ("a.flac", "a_again.flac"):
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title=name, media_root_id=r.id,
                           audio_path=name, uploaded_by=u.id, source_type="upload",
                           status="processing", duration_seconds=300)
            s.add(live)
            await s.commit()
            ids.append(live.id)
        s.add(SetFingerprint(live_set_id=ids[0], fingerprint_hash=legacy,
                             duration_seconds=float(data["duration"])))
        await s.commit()

    await fingerprint_audio(str(ids[1]))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, ids[1])).duplicate_of == ids[0]
        row = (await s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == ids[1]),
        )).scalars().one()
        assert row.fingerprint_hash == legacy


async def test_identical_short_clips_are_flagged_duplicate(
    tmp_path: Path, fpcalc_present, require_tools,
):
    """A 5 s clip is too short for the fuzzy matcher (needs ~15 s of chromaprint
    items), so identical short files must match on the exact legacy digest."""
    require_tools("ffmpeg")
    clip = tmp_path / "clip.flac"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
           str(clip)]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: ASYNC221, S603
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = []
        for _ in range(2):
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                           audio_path="clip.flac", uploaded_by=u.id, source_type="upload",
                           status="processing", duration_seconds=5)
            s.add(live)
            await s.commit()  # distinct created_at, original first
            ids.append(live.id)

    for sid in ids:
        await fingerprint_audio(str(sid))

    async with session_factory()() as s:
        assert (await s.get(LiveSet, ids[0])).duplicate_of is None
        assert (await s.get(LiveSet, ids[1])).duplicate_of == ids[0]


# --- R28 / R31 (C2, C6): upgrade-attempt arrivals are judged against their target only.


async def test_upgrade_attempt_matches_its_target_past_the_compare_cap(
    tmp_path: Path, monkeypatch,
):
    """The target sits behind many similar-length sets (here: the cap is 2
    and three decoys come first); its own re-encode must still match it."""
    monkeypatch.setattr("setvault_core.services.set_match.MAX_COMPARES", 2)
    for seed in (41, 42, 43):
        _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(seed)))
        await fingerprint_audio(str(await _make_set(tmp_path)))
    items = _random_items(44)
    _fake_fpcalc(monkeypatch, 0, _items_json(items))
    target = await _make_set(tmp_path)
    await fingerprint_audio(str(target))
    arrival = await _make_set(tmp_path)
    # A re-encode: a few bits differ, and it starts 8 items (~1 s) later.
    reenc = [v ^ 1 for v in items[8:]]
    _fake_fpcalc(monkeypatch, 0, _items_json(reenc))

    await fingerprint_audio(str(arrival), upgrade_target_id=target)

    async with session_factory()() as s:
        live = await s.get(LiveSet, arrival)
        assert live.duplicate_of == target
        assert live.match_offset_seconds == pytest.approx(8 / 8.0769, abs=0.05)


async def test_upgrade_attempt_is_not_stolen_by_an_earlier_twin(
    tmp_path: Path, monkeypatch,
):
    """An earlier set with the same audio (twin) is not a duplicate itself;
    the library-wide match would point at it. The upgrade attempt for the
    later target must point at the target."""
    items = _random_items(45)
    _fake_fpcalc(monkeypatch, 0, _items_json(items))
    twin = await _make_set(tmp_path)
    target = await _make_set(tmp_path)
    await fingerprint_audio(str(twin))
    await fingerprint_audio(str(target))
    async with session_factory()() as s:  # e.g. kept as its own set by an admin
        (await s.get(LiveSet, target)).duplicate_of = None
        await s.commit()
    arrival = await _make_set(tmp_path)

    await fingerprint_audio(str(arrival), upgrade_target_id=target)

    async with session_factory()() as s:
        assert (await s.get(LiveSet, arrival)).duplicate_of == target


async def test_upgrade_attempt_of_other_audio_points_nowhere(tmp_path: Path, monkeypatch):
    """Different audio from the target: no duplicate_of, even though the
    arrival matches another set in the library."""
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(46)))
    target = await _make_set(tmp_path)
    await fingerprint_audio(str(target))
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(47)))
    other = await _make_set(tmp_path)
    await fingerprint_audio(str(other))
    arrival = await _make_set(tmp_path)

    await fingerprint_audio(str(arrival), upgrade_target_id=target)

    async with session_factory()() as s:
        live = await s.get(LiveSet, arrival)
        assert live.duplicate_of is None and live.match_offset_seconds is None


async def test_upgrade_attempt_never_restores_a_recycled_lookalike(
    tmp_path: Path, monkeypatch,
):
    """C6: a scheduled candidate that matches a recycled set S (not its
    target) must never undelete S nor recycle itself."""
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(48)))
    target = await _make_set(tmp_path)
    await fingerprint_audio(str(target))
    _fake_fpcalc(monkeypatch, 0, _items_json(_random_items(49)))
    recycled = await _make_set(tmp_path)
    await fingerprint_audio(str(recycled))
    await _set_quality(recycled, "lossless", True, deleted=True)
    arrival = await _make_set(tmp_path)
    await _set_quality(arrival, "ok", False)  # worse: the library rule would restore S

    await fingerprint_audio(str(arrival), upgrade_target_id=target)

    async with session_factory()() as s:
        assert (await s.get(LiveSet, recycled)).deleted_at is not None
        live = await s.get(LiveSet, arrival)
        assert live.deleted_at is None and live.duplicate_of is None


async def test_upgrade_attempt_uses_legacy_hash_when_target_has_no_raw(
    tmp_path: Path, monkeypatch,
):
    stdout = _items_json(_random_items(50), duration=3.0)
    target = await _make_set(tmp_path)
    await _add_legacy_row(target, _legacy_digest(stdout), 3.0)
    _fake_fpcalc(monkeypatch, 0, stdout)
    arrival = await _make_set(tmp_path)

    await fingerprint_audio(str(arrival), upgrade_target_id=target)

    async with session_factory()() as s:
        live = await s.get(LiveSet, arrival)
        assert live.duplicate_of == target and live.match_offset_seconds == 0


def _track_open_connections(monkeypatch) -> tuple[list[int], list[int]]:
    """Count checked-out DB connections; returns (during fpcalc, during compare)."""
    from setvault_core.services import set_match
    from sqlalchemy import event

    engine = session_factory().kw["bind"].sync_engine
    open_count = [0]

    def _out(*_a):
        open_count[0] += 1

    def _in(*_a):
        open_count[0] -= 1

    event.listen(engine, "checkout", _out)
    event.listen(engine, "checkin", _in)
    seen_fpcalc: list[int] = []
    seen_compare: list[int] = []

    import setvault_core.services.audio_match as am
    real_run = am.subprocess.run

    def run(*a, **k):
        seen_fpcalc.append(open_count[0])
        return real_run(*a, **k)

    monkeypatch.setattr(am.subprocess, "run", run)
    real_compare = set_match.compare

    def compare(*a, **k):
        seen_compare.append(open_count[0])
        return real_compare(*a, **k)

    monkeypatch.setattr(set_match, "compare", compare)
    return seen_fpcalc, seen_compare


@pytest.mark.parametrize("upgrade", [False, True])
async def test_no_db_connection_held_during_fpcalc_or_compare(
    tmp_path: Path, monkeypatch, upgrade,
):
    items = _random_items(77)
    _fake_fpcalc(monkeypatch, 0, _items_json(items))
    original = await _make_set(tmp_path)
    await fingerprint_audio(str(original))
    # A re-encode: a few flipped bits, so the legacy digest differs and the
    # fuzzy compare (not the exact-hash shortcut) decides.
    _fake_fpcalc(monkeypatch, 0, _items_json([v ^ 1 if i % 10 == 0 else v
                                              for i, v in enumerate(items)]))
    arrival = await _make_set(tmp_path)
    seen_fpcalc, seen_compare = _track_open_connections(monkeypatch)

    if upgrade:
        await fingerprint_audio(str(arrival), upgrade_target_id=original)
    else:
        await fingerprint_audio(str(arrival))

    assert seen_fpcalc and seen_compare
    assert set(seen_fpcalc) == {0}
    assert set(seen_compare) == {0}
    async with session_factory()() as s:
        assert (await s.get(LiveSet, arrival)).duplicate_of == original

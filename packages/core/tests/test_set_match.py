import array
import os
import random
import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.identity import User
from setvault_core.services.audio_match import MATCHER_VERSION, raw_to_bytes
from setvault_core.services.set_match import find_original_match
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


def _items(seed: int, n: int = 2000) -> array.array:
    rng = random.Random(seed)  # noqa: S311
    return array.array("I", (rng.getrandbits(32) for _ in range(n)))


class _World:
    def __init__(self, s, user, root):
        self.s, self.user, self.root = s, user, root

    async def add(self, raw=None, duration=300.0, version=MATCHER_VERSION, **kw) -> LiveSet:
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=self.root.id,
                       audio_path="a.flac", uploaded_by=self.user.id, source_type="upload",
                       status="published", **kw)
        self.s.add(live)
        await self.s.flush()
        self.s.add(SetFingerprint(
            live_set_id=live.id, fingerprint_hash=uuid.uuid4().hex, duration_seconds=duration,
            raw=raw_to_bytes(raw) if raw is not None else None,
            raw_version=version if raw is not None else None,
        ))
        await self.s.commit()  # separate commits keep created_at ordered
        return live


@pytest.fixture
async def world(tmp_path):
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        yield _World(s, u, r)


async def test_no_candidates_returns_none(world):
    arrival = await world.add(_items(1))
    assert await find_original_match(world.s, arrival, _items(1), 300.0) is None


async def test_finds_same_audio_with_offset(world):
    a = _items(1)
    original = await world.add(a)
    arrival = await world.add()
    # The arrival is A without its first 100 items.
    hit = await find_original_match(world.s, arrival, a[100:], 290.0)
    assert hit is not None
    assert hit[0].id == original.id
    assert hit[1].offset_seconds == pytest.approx(100 / 8.0769, abs=0.5)


async def test_unrelated_audio_is_not_a_match(world):
    await world.add(_items(1))
    arrival = await world.add()
    assert await find_original_match(world.s, arrival, _items(2), 300.0) is None


async def test_prefers_original_over_kept_duplicate(world):
    a = _items(1)
    original = await world.add(a)
    await world.add(a, duplicate_of=original.id)
    arrival = await world.add()
    hit = await find_original_match(world.s, arrival, a, 300.0)
    assert hit is not None and hit[0].id == original.id


async def test_earliest_original_wins(world):
    a = _items(1)
    first = await world.add(a)
    await world.add(a)  # a second un-flagged copy
    arrival = await world.add()
    hit = await find_original_match(world.s, arrival, a, 300.0)
    assert hit[0].id == first.id


async def test_live_match_beats_older_soft_deleted_one(world):
    a = _items(1)
    await world.add(a, deleted_at=datetime.now(UTC))
    live_one = await world.add(a)
    arrival = await world.add()
    hit = await find_original_match(world.s, arrival, a, 300.0)
    assert hit[0].id == live_one.id


async def test_soft_deleted_match_used_when_no_live_one(world):
    a = _items(1)
    gone = await world.add(a, deleted_at=datetime.now(UTC))
    arrival = await world.add()
    hit = await find_original_match(world.s, arrival, a, 300.0)
    assert hit[0].id == gone.id


async def test_duration_prefilter(world):
    a = _items(1)
    await world.add(a, duration=300.0)
    arrival = await world.add()
    # 300 s vs 3000 s is far outside max(10%, 60 s).
    assert await find_original_match(world.s, arrival, a, 3000.0) is None


async def test_duration_tolerance_uses_larger_of_pct_and_seconds(world):
    a = _items(1)
    original = await world.add(a, duration=100.0)
    arrival = await world.add()
    # 150 s is 50% off but only 50 s: inside the 60 s floor.
    hit = await find_original_match(world.s, arrival, a, 150.0)
    assert hit is not None and hit[0].id == original.id


async def test_ignores_other_matcher_versions_and_missing_raw(world):
    a = _items(1)
    await world.add(a, version=MATCHER_VERSION + 1)
    await world.add()  # legacy row without raw
    arrival = await world.add()
    assert await find_original_match(world.s, arrival, a, 300.0) is None


async def test_legacy_hash_only_row_matches_by_hash(world):
    legacy = await world.add()  # no raw
    fp = (await world.s.execute(
        select(SetFingerprint).where(SetFingerprint.live_set_id == legacy.id),
    )).scalars().one()
    arrival = await world.add()
    hit = await find_original_match(world.s, arrival, _items(1), 301.0,
                                    legacy_hash=fp.fingerprint_hash)
    assert hit is not None and hit[0].id == legacy.id
    assert hit[1].offset_seconds == 0.0


async def test_compare_cap_stops_and_logs(world, monkeypatch, caplog):
    from setvault_core.services import set_match

    for seed in range(2, 6):  # four unrelated candidates
        await world.add(_items(seed))
    arrival = await world.add()
    calls = []
    real = set_match.compare
    monkeypatch.setattr(set_match, "compare", lambda a, b: calls.append(1) or real(a, b))
    monkeypatch.setattr(set_match, "MAX_COMPARES", 2)

    with caplog.at_level("WARNING", logger="setvault_core.services.set_match"):
        assert await find_original_match(world.s, arrival, _items(1), 300.0) is None
    assert len(calls) == 2
    assert "cap" in caplog.text


async def test_exact_legacy_hash_matches_row_that_has_raw(world):
    # A short clip: the fuzzy compare can't match, but the digest is identical.
    a = await world.add(_items(1, 40), duration=5.0)
    async with world.s.begin_nested():
        fp = (await world.s.execute(
            select(SetFingerprint).where(SetFingerprint.live_set_id == a.id),
        )).scalar_one()
        fp.fingerprint_hash = "samedigest"
    await world.s.commit()
    new = await world.add(_items(2, 40), duration=5.0)
    got = await find_original_match(
        world.s, new, _items(2, 40), 5.0, legacy_hash="samedigest")
    assert got is not None and got[0].id == a.id

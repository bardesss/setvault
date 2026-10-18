"""Ingest-time upgrade decision (Phase 7D Task 8): an arrival upgrades an
existing set, is held as a duplicate, is discarded (upgrade-attempt rips) or
is simply published."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.ready import mark_ready
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.services import set_upgrade
from setvault_core.services.system_config import get_config
from setvault_core.services.upgrade_decision import decide_arrival
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture(autouse=True)
def _no_webhooks(monkeypatch):
    async def fake(live, event):
        return None

    monkeypatch.setattr(set_upgrade, "fan_out_webhooks", fake)


@pytest.fixture
async def auto_upgrades():
    """Yields a setter for the library-wide switch; always restores it to on."""
    async def _set(on: bool) -> None:
        async with session_factory()() as s:
            cfg = await get_config(s)
            cfg.auto_upgrades_enabled = on
            await s.commit()

    await _set(True)
    yield _set
    await _set(True)


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


async def _seed(
    tmp_path: Path, *, target_tier: str | None = "ok", arrival_tier: str = "lossless",
    target_lossless: bool | None = False, arrival_lossless: bool | None = True,
    upgrades_enabled: bool = True, target_deleted: bool = False, duplicate: bool = True,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A published target and a processed draft arrival flagged as its duplicate."""
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path), enabled=True)
        s.add_all([u, r])
        await s.flush()
        tid, aid = uuid.uuid4(), uuid.uuid4()
        target = LiveSet(
            id=tid, slug=f"t-{tid.hex[:6]}", title="Set X", media_root_id=r.id,
            audio_path=f"originals/{tid}/old.mp3", streaming_path=f"stream/{tid}.opus",
            waveform_path=f"waveform/{tid}.json", uploaded_by=u.id, status="published",
            source_type="upload", audio_codec="mp3", audio_lossless=target_lossless,
            quality_tier=target_tier, upgrades_enabled=upgrades_enabled,
            quality_measured_at=datetime.now(UTC) if target_tier else None,
            deleted_at=datetime.now(UTC) if target_deleted else None,
        )
        arrival = LiveSet(
            id=aid, slug=f"a-{aid.hex[:6]}", title="Set X again", media_root_id=r.id,
            audio_path=f"originals/{aid}/new.flac", streaming_path=f"stream/{aid}.opus",
            waveform_path=f"waveform/{aid}.json", uploaded_by=u.id, status="processing",
            source_type="upload", audio_codec="flac", audio_lossless=arrival_lossless,
            quality_tier=arrival_tier, quality_measured_at=datetime.now(UTC),
            duplicate_of=tid if duplicate else None,
        )
        s.add(target)
        await s.flush()
        s.add(arrival)
        await s.commit()
    for sid in (tid, aid):
        async with session_factory()() as s:
            live = await s.get(LiveSet, sid)
            for rel in (live.audio_path, live.streaming_path, live.waveform_path):
                _touch(tmp_path, rel)
    return tid, aid


async def _events(tid: uuid.UUID) -> list[SetUpgradeEvent]:
    async with session_factory()() as s:
        return list((await s.execute(
            select(SetUpgradeEvent).where(SetUpgradeEvent.live_set_id == tid)
        )).scalars().all())


async def _decide(aid: uuid.UUID, **kw) -> str:
    async with session_factory()() as s:
        arrival = await s.get(LiveSet, aid)
        return await decide_arrival(s, arrival, **kw)


async def test_better_duplicate_upload_upgrades_existing_set(tmp_path, auto_upgrades):
    tid, aid = await _seed(tmp_path)

    assert await mark_ready(str(aid), trigger="upload") is False

    async with session_factory()() as s:
        target = await s.get(LiveSet, tid)
        arrival = await s.get(LiveSet, aid)
        assert target.quality_tier == "lossless"
        assert target.audio_path == f"originals/{aid}/new.flac"
        assert target.status == "published" and target.deleted_at is None
        # The arrival row now holds the old copy, in the recycle bin.
        assert arrival.deleted_at is not None
        assert arrival.audio_path == f"originals/{tid}/old.mp3"
    [event] = await _events(tid)
    assert (event.outcome, event.trigger) == ("upgraded", "upload")


async def test_equal_duplicate_is_held(tmp_path, auto_upgrades):
    tid, aid = await _seed(tmp_path, target_tier="lossless", target_lossless=True)

    assert await mark_ready(str(aid)) is False

    async with session_factory()() as s:
        arrival = await s.get(LiveSet, aid)
        target = await s.get(LiveSet, tid)
        # Held for the Duplicates page: a draft still flagged, nothing swapped.
        assert arrival.deleted_at is None and arrival.status != "published"
        assert arrival.duplicate_of == tid
        assert target.audio_path == f"originals/{tid}/old.mp3"
    assert await _events(tid) == []


async def test_better_duplicate_of_locked_set_is_held(tmp_path, auto_upgrades):
    tid, aid = await _seed(tmp_path, upgrades_enabled=False)
    assert await _decide(aid, upgrade_target_id=None, trigger="upload") == "held"

    # Library-wide automatic upgrades off holds it the same way.
    tid2, aid2 = await _seed(tmp_path)
    await auto_upgrades(False)
    assert await _decide(aid2, upgrade_target_id=None, trigger="upload") == "held"

    async with session_factory()() as s:
        for t in (tid, tid2):
            assert (await s.get(LiveSet, t)).quality_tier == "ok"
        for a in (aid, aid2):
            assert (await s.get(LiveSet, a)).deleted_at is None
    assert await _events(tid) == [] and await _events(tid2) == []


async def test_unmeasured_set_is_not_upgraded(tmp_path, auto_upgrades):
    tid, aid = await _seed(tmp_path, target_tier=None, target_lossless=None)

    assert await _decide(aid, upgrade_target_id=None, trigger="upload") == "held"

    async with session_factory()() as s:
        assert (await s.get(LiveSet, tid)).quality_tier is None
        assert (await s.get(LiveSet, aid)).deleted_at is None


async def test_lossy_never_replaces_lossless(tmp_path, auto_upgrades):
    """A better-rated lossy file never beats a lossless-container file."""
    _tid, aid = await _seed(tmp_path, target_tier="ok", target_lossless=True,
                            arrival_tier="high", arrival_lossless=False)
    assert await _decide(aid, upgrade_target_id=None, trigger="upload") == "held"


async def test_no_duplicate_is_published(tmp_path, auto_upgrades):
    _tid, aid = await _seed(tmp_path, duplicate=False)
    assert await _decide(aid, upgrade_target_id=None, trigger="upload") == "publish"
    assert await mark_ready(str(aid)) is True
    async with session_factory()() as s:
        assert (await s.get(LiveSet, aid)).status == "published"


async def test_recycled_arrival_is_a_no_op(tmp_path, auto_upgrades):
    """R1: the fingerprint stage already recycled the arrival (it matched a
    recycled original); never upgrade from it, never publish it."""
    tid, aid = await _seed(tmp_path)
    async with session_factory()() as s:
        (await s.get(LiveSet, aid)).deleted_at = datetime.now(UTC)
        await s.commit()

    assert await _decide(aid, upgrade_target_id=None, trigger="upload") == "held"
    assert await _decide(aid, upgrade_target_id=tid, trigger="scheduled") == "held"
    assert await mark_ready(str(aid)) is False
    async with session_factory()() as s:
        assert (await s.get(LiveSet, tid)).quality_tier == "ok"
        arrival = await s.get(LiveSet, aid)
        assert arrival is not None and arrival.status != "published"


async def test_upgrade_rip_discarded_when_target_deleted_or_locked(tmp_path, auto_upgrades):
    # Target in the recycle bin.
    tid, aid = await _seed(tmp_path, target_deleted=True)
    assert await _decide(aid, upgrade_target_id=tid, trigger="scheduled") == "discarded"
    # Target gone altogether.
    _tid, aid_missing = await _seed(tmp_path, duplicate=False)
    assert await _decide(aid_missing, upgrade_target_id=uuid.uuid4(),
                         trigger="scheduled") == "discarded"
    # Target's upgrades switched off.
    tid_locked, aid_locked = await _seed(tmp_path, upgrades_enabled=False)
    assert await _decide(aid_locked, upgrade_target_id=tid_locked,
                         trigger="scheduled") == "discarded"
    # Automatic upgrades off library-wide.
    tid_off, aid_off = await _seed(tmp_path)
    await auto_upgrades(False)
    assert await _decide(aid_off, upgrade_target_id=tid_off, trigger="scheduled") == "discarded"

    async with session_factory()() as s:
        for a in (aid, aid_missing, aid_locked, aid_off):
            assert await s.get(LiveSet, a) is None
        assert (await s.get(LiveSet, tid_locked)).quality_tier == "ok"
    assert [e.reason for e in await _events(tid)] == ["target unavailable"]
    assert [e.reason for e in await _events(tid_locked)] == ["upgrades off"]
    assert [e.reason for e in await _events(tid_off)] == ["upgrades off"]
    assert not (tmp_path / f"originals/{aid_locked}/new.flac").exists()


async def test_upgrade_rip_of_different_or_worse_audio_is_discarded(tmp_path, auto_upgrades):
    tid, aid = await _seed(tmp_path, duplicate=False)
    assert await _decide(aid, upgrade_target_id=tid, trigger="scheduled") == "discarded"
    tid2, aid2 = await _seed(tmp_path, target_tier="lossless", target_lossless=True)
    assert await _decide(aid2, upgrade_target_id=tid2, trigger="scheduled") == "discarded"

    assert [(e.outcome, e.reason) for e in await _events(tid)] == [
        ("rejected", "different audio")]
    assert [(e.outcome, e.reason) for e in await _events(tid2)] == [
        ("rejected", "not better")]
    async with session_factory()() as s:
        assert await s.get(LiveSet, aid) is None and await s.get(LiveSet, aid2) is None


async def test_upgrade_rip_of_better_audio_upgrades(tmp_path, auto_upgrades):
    tid, aid = await _seed(tmp_path)
    assert await _decide(aid, upgrade_target_id=tid, trigger="scheduled") == "upgraded"
    [event] = await _events(tid)
    assert (event.outcome, event.trigger) == ("upgraded", "scheduled")

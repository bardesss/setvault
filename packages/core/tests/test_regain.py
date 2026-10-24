import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import regain
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.services.loudness import gain_for
from setvault_core.services.system_config import get_config


@pytest.fixture(autouse=True)
async def _engine_and_target():
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        config = await get_config(s)
        before = config.loudness_target_lufs
        config.loudness_target_lufs = -14.0
        await s.commit()
    yield
    async with session_factory()() as s:
        (await get_config(s)).loudness_target_lufs = before
        await s.commit()


async def _seed(tmp_path: Path, rows: dict[str, dict]) -> dict[str, uuid.UUID]:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        ids = {}
        for name, fields in rows.items():
            values = {"status": "published", "streaming_path": f"stream/{name}.opus", **fields}
            live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title=name, media_root_id=r.id,
                           audio_path=f"{name}.flac", uploaded_by=u.id, source_type="upload",
                           **values)
            s.add(live)
            await s.flush()
            ids[name] = live.id
        await s.commit()
        return ids


def _fake_transcode(
    monkeypatch, fail: set[uuid.UUID] = frozenset(), discard: set[uuid.UUID] = frozenset(),
) -> list[uuid.UUID]:
    """Stand-in for transcode_audio: records the call and stores the gain the
    real transcode would apply at the -14 target (or commits nothing and
    reports "discarded")."""
    calls: list[uuid.UUID] = []

    async def _transcode(live_set_id: str) -> str:
        sid = uuid.UUID(live_set_id)
        calls.append(sid)
        if sid in fail:
            raise RuntimeError("ffmpeg failed")
        if sid in discard:
            return "discarded"
        async with session_factory()() as s:
            live = await s.get(LiveSet, sid)
            live.stream_gain_db = gain_for(live.normalized_lufs, -14.0)
            await s.commit()
        return "done"

    monkeypatch.setattr(regain, "transcode_audio", _transcode)
    return calls


async def test_regain_only_sets_past_threshold(tmp_path: Path, monkeypatch):
    ids = await _seed(tmp_path, {
        "never": {"normalized_lufs": -8.0},  # null gain, wants -6.0
        "stale": {"normalized_lufs": -8.0, "stream_gain_db": -2.0},  # wants -6.0
        "done": {"normalized_lufs": -8.0, "stream_gain_db": -6.0},
        "close": {"normalized_lufs": -14.4},  # wants 0.4: within 0.5 dB
        "bogus": {"normalized_lufs": -70.0},  # no gain wanted
        "deleted": {"normalized_lufs": -8.0, "deleted_at": datetime.now(UTC)},
        "processing": {"normalized_lufs": -8.0, "status": "processing"},
    })
    calls = _fake_transcode(monkeypatch)

    result = await regain.regain_library()

    assert result == {"checked": 5, "regained": 2, "discarded": 0, "failed": 0}
    assert sorted(calls) == sorted([ids["never"], ids["stale"]])


async def test_regain_second_run_does_nothing(tmp_path: Path, monkeypatch):
    await _seed(tmp_path, {
        "a": {"normalized_lufs": -8.0},
        "b": {"normalized_lufs": -24.0, "stream_gain_db": 0.0},
    })
    _fake_transcode(monkeypatch)
    assert await regain.regain_library() == {
        "checked": 2, "regained": 2, "discarded": 0, "failed": 0,
    }

    calls = _fake_transcode(monkeypatch)
    assert await regain.regain_library() == {
        "checked": 2, "regained": 0, "discarded": 0, "failed": 0,
    }
    assert calls == []


async def test_regain_failure_counts_and_continues(tmp_path: Path, monkeypatch):
    ids = await _seed(tmp_path, {
        "bad": {"normalized_lufs": -8.0},
        "good": {"normalized_lufs": -8.0},
    })
    calls = _fake_transcode(monkeypatch, fail={ids["bad"]})

    result = await regain.regain_library()

    assert result == {"checked": 2, "regained": 1, "discarded": 0, "failed": 1}
    assert sorted(calls) == sorted(ids.values())
    async with session_factory()() as s:
        assert (await s.get(LiveSet, ids["good"])).stream_gain_db == -6.0
        assert (await s.get(LiveSet, ids["bad"])).stream_gain_db is None


async def test_regain_counts_discarded_transcodes(tmp_path: Path, monkeypatch):
    """A transcode that commits no stream (e.g. an upgrade swapped the set
    meanwhile) is not counted as re-gained."""
    ids = await _seed(tmp_path, {
        "swapped": {"normalized_lufs": -8.0},
        "good": {"normalized_lufs": -8.0},
    })
    calls = _fake_transcode(monkeypatch, discard={ids["swapped"]})

    result = await regain.regain_library()

    assert result == {"checked": 2, "regained": 1, "discarded": 1, "failed": 0}
    assert sorted(calls) == sorted(ids.values())

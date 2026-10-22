import uuid
from types import SimpleNamespace

import pytest
from setvault_core.models.identity import User
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.services import discoveries as svc
from setvault_core.services.passwords import hash_password
from setvault_ingest_sources.base import Candidate
from sqlalchemy import select


async def _user(session):
    u = User(
        email=f"u-{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
        display_name="u", password_hash=hash_password("aaaaaaaa"),
    )
    session.add(u)
    await session.flush()
    return u


def _c(ext, title, tier, dur=3600):
    return Candidate("soundcloud", ext, title, "Bicep", dur, None,
                     f"https://soundcloud.com/x/{ext}", expected_tier=tier)


@pytest.mark.asyncio
async def test_monitor_auto_ingests_only_best_copy_per_group(session, monkeypatch):
    ripped = []

    async def fake_ingest(s, *, monitor, candidate):
        ripped.append(candidate.external_id)
        return SimpleNamespace(id=None), False

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(svc, "_ingest_candidate", fake_ingest)
    monkeypatch.setattr(svc, "_notify_owner", noop)
    u = await _user(session)
    m = Monitor(kind="query", query_text="Bicep", owner_user_id=u.id, enabled=True, per_poll_cap=5)
    session.add(m)
    await session.flush()

    cands = [
        _c("lo", "Bicep Live at Field Day", "low"),
        _c("unk", "Bicep Live at Field Day", None),
        _c("best", "Bicep - Live at Field Day (SBD)", "lossless", dur=3700),
        _c("other", "Bicep Printworks 2022", "ok"),          # different set
        _c("long", "Bicep Live at Field Day", "high", dur=7200),  # duration too far
    ]
    summary = await svc.process_candidates(session, monitor=m, candidates=cands)
    assert sorted(ripped) == ["best", "long", "other"]
    assert summary["auto_ingested"] == 3 and summary["pending_review"] == 2
    rows = {r.external_id: r.status for r in (await session.execute(
        select(MonitorDiscovery).where(MonitorDiscovery.monitor_id == m.id))).scalars()}
    assert rows["lo"] == rows["unk"] == "pending_review"
    assert rows["best"] == "auto_ingested"


def test_candidates_without_duration_are_each_their_own_group():
    from setvault_core.services.audio_quality import TIERS
    from setvault_core.services.quality_profile import QualityProfile

    profile = QualityProfile(order=TIERS, cutoff="lossless")
    items = [
        (_c("a", "Bicep Live at Field Day", "low", dur=None), "high"),
        (_c("b", "Bicep Live at Field Day", "lossless", dur=None), "high"),
        (_c("c", "Bicep Live at Field Day", "ok", dur=0), "high"),
    ]
    # Without a duration "same set" can't be told, so none is dropped as a
    # worse copy of another: every one is the best of its own group.
    assert svc._best_copies(profile, items) == {0, 1, 2}


def test_same_title_on_different_nights_stays_separate():
    from setvault_core.services.audio_quality import TIERS
    from setvault_core.services.quality_profile import QualityProfile

    profile = QualityProfile(order=TIERS, cutoff="lossless")
    items = [
        (_c("n1", "Bicep Live at Field Day", "low", dur=3600), "high"),
        (_c("n2", "Bicep Live at Field Day", "lossless", dur=5400), "high"),  # 50% longer
        (_c("n1b", "Bicep Live at Field Day", "high", dur=3650), "high"),  # n1 again
    ]
    assert svc._best_copies(profile, items) == {1, 2}

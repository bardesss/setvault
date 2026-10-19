import uuid

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

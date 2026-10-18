from __future__ import annotations

import pytest
from setvault_core.models.upgrades import SetUpgradeEvent, already_tried


@pytest.mark.asyncio
async def test_already_tried_true_after_rejected_event(session_with_set):
    session, live_id, _ = session_with_set
    assert not await already_tried(
        session, live_id, source_kind="soundcloud", external_id="abc"
    )
    session.add(SetUpgradeEvent(
        live_set_id=live_id, trigger="scheduled", outcome="rejected",
        reason="not better", candidate_source_kind="soundcloud",
        candidate_external_id="abc",
    ))
    await session.flush()

    assert await already_tried(session, live_id, source_kind="soundcloud", external_id="abc")
    assert not await already_tried(session, live_id, source_kind="soundcloud", external_id="zzz")
    assert not await already_tried(session, live_id, source_kind="mixcloud", external_id="abc")

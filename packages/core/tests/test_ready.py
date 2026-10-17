import os
import uuid

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.ready import mark_ready
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.engagement import ActivityEvent
from setvault_core.models.identity import User
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def test_mark_ready_publishes_set_and_logs_activity(tmp_path):
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                       audio_path="x", uploaded_by=u.id, source_type="upload",
                       status="processing")
        s.add(live)
        await s.commit()
        sid = live.id

    await mark_ready(str(sid))

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.status == "published"
        events = (await s.execute(
            select(ActivityEvent).where(ActivityEvent.subject_id == sid),
        )).scalars().all()
        assert any(e.kind == "set.published" for e in events)


async def test_mark_ready_holds_duplicates_as_draft(tmp_path):
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()
        original = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                           audio_path="x", uploaded_by=u.id, source_type="upload",
                           status="published")
        s.add(original)
        await s.flush()
        dup = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                      audio_path="y", uploaded_by=u.id, source_type="upload",
                      status="draft", duplicate_of=original.id)
        s.add(dup)
        await s.commit()
        sid = dup.id

    assert await mark_ready(str(sid)) is False

    async with session_factory()() as s:
        row = await s.get(LiveSet, sid)
        assert row.status == "draft"
        events = (await s.execute(
            select(ActivityEvent).where(ActivityEvent.subject_id == sid),
        )).scalars().all()
        assert not any(e.kind == "set.published" for e in events)

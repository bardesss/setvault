"""reapply_naming_template: the admin "Re-apply template" job walks every
live set on a root through apply_naming_to_set."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.reapply_naming import reapply_naming_template
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.system import AuditEvent
from sqlalchemy import delete, select


@pytest.fixture(autouse=True)
async def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])
    yield
    async with session_factory()() as s:
        await s.execute(delete(AuditEvent).where(
            AuditEvent.action == "media_root.naming_reapplied"))
        await s.commit()


async def test_reapply_renames_all_sets_on_root(tmp_path: Path):
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path),
                      enabled=True, naming_template="sets/{Slug}.{Ext}")
        s.add_all([u, r])
        await s.flush()
        rows = {
            "one": LiveSet(slug="one", title="one", media_root_id=r.id,
                           audio_path="originals/1/a.flac", uploaded_by=u.id),
            "two": LiveSet(slug="two", title="two", media_root_id=r.id,
                           audio_path="originals/2/b.mp3", uploaded_by=u.id),
            # Already named per the template.
            "three": LiveSet(slug="three", title="three", media_root_id=r.id,
                             audio_path="sets/three.opus", uploaded_by=u.id),
            # Source file missing on disk.
            "four": LiveSet(slug="four", title="four", media_root_id=r.id,
                            audio_path="originals/4/gone.flac", uploaded_by=u.id),
            # In the recycle bin: not touched.
            "five": LiveSet(slug="five", title="five", media_root_id=r.id,
                            audio_path="originals/5/e.flac", uploaded_by=u.id,
                            deleted_at=datetime.now(UTC)),
        }
        s.add_all(rows.values())
        await s.commit()
        root_id = r.id
        ids = {k: v.id for k, v in rows.items()}
    for rel in ("originals/1/a.flac", "originals/2/b.mp3", "sets/three.opus",
                "originals/5/e.flac"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(rel.encode())

    summary = await reapply_naming_template(str(root_id))

    assert summary == {"renamed": 2, "unchanged": 1, "skipped": 1, "errors": 0}
    async with session_factory()() as s:
        paths = {k: (await s.get(LiveSet, v)).audio_path for k, v in ids.items()}
        assert paths == {
            "one": "sets/one.flac", "two": "sets/two.mp3", "three": "sets/three.opus",
            "four": "originals/4/gone.flac", "five": "originals/5/e.flac",
        }
        audit = (await s.execute(select(AuditEvent).where(
            AuditEvent.action == "media_root.naming_reapplied",
            AuditEvent.target_id == str(root_id),
        ))).scalars().one()
        assert audit.after == summary
    assert (tmp_path / "sets/one.flac").read_bytes() == b"originals/1/a.flac"
    assert (tmp_path / "sets/two.mp3").read_bytes() == b"originals/2/b.mp3"
    assert not (tmp_path / "originals/1/a.flac").exists()
    assert (tmp_path / "originals/5/e.flac").exists()


async def test_reapply_without_template_does_nothing(tmp_path: Path):
    async with session_factory()() as s:
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path), enabled=True)
        s.add(r)
        await s.commit()
        root_id = r.id

    summary = await reapply_naming_template(str(root_id))

    assert summary == {"renamed": 0, "unchanged": 0, "skipped": 0, "errors": 0}

"""0027 data migration: soft-deleted sets get a fresh 14-day purge window."""
import importlib.util
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from sqlalchemy import text

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "infra/migrations/versions/0027_purge_grace_reset.py"
)


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


def _sql() -> str:
    spec = importlib.util.spec_from_file_location("m0027", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0027_purge_grace_reset"
    return mod.PURGE_GRACE_RESET_SQL


async def test_resets_deleted_sets_only():
    now = datetime.now(UTC)
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role="admin")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path="/media/x",
                      enabled=True, default_for_ingest=True)
        s.add_all([u, r])
        await s.flush()

        def mk(**kw):
            return LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t", media_root_id=r.id,
                           audio_path="a.mp3", uploaded_by=u.id, source_type="upload",
                           status="published", **kw)

        expired = mk(deleted_at=now - timedelta(days=30), purge_after_at=now - timedelta(days=16))
        no_window = mk(deleted_at=now - timedelta(days=1), purge_after_at=None)
        far = mk(deleted_at=now, purge_after_at=now + timedelta(days=60))
        live = mk()
        s.add_all([expired, no_window, far, live])
        await s.commit()
        ids = (expired.id, no_window.id, far.id, live.id)
        far_before = far.purge_after_at

        await s.execute(text(_sql()))
        await s.commit()

        s.expire_all()
        e, n, f, lv = [await s.get(LiveSet, i) for i in ids]
        floor = datetime.now(UTC) + timedelta(days=14) - timedelta(minutes=5)
        assert e.purge_after_at >= floor
        assert n.purge_after_at >= floor
        assert f.purge_after_at == far_before  # longer windows are kept
        assert lv.purge_after_at is None  # not deleted: untouched

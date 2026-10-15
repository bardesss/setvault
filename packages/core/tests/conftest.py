import os
import shutil
import uuid

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.ingest_sources import IngestSourceState
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.models.tracklist import TracklistEntry
from setvault_core.services.passwords import hash_password
from sqlalchemy import delete
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def _get_test_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session", autouse=True)
def _check_db_url():
    """Skip entire session if TEST_DATABASE_URL is not set."""
    url = _get_test_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)


@pytest.fixture
def require_tools():
    """Skip when audio CLI tools are missing; fail instead in CI.

    CI sets ``SETVAULT_REQUIRE_AUDIO_TOOLS=1`` so the ffmpeg/audiowaveform/
    fpcalc pipeline tests can never silently skip there.
    """
    def _require(*tools: str) -> None:
        missing = [t for t in tools if not shutil.which(t)]
        if not missing:
            return
        msg = f"{' + '.join(missing)} not installed"
        if os.environ.get("SETVAULT_REQUIRE_AUDIO_TOOLS") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
    return _require


@pytest.fixture
async def session():
    """Provide a fresh AsyncSession per test using NullPool to avoid event-loop conflicts."""
    url = _get_test_url()
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def uid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
async def session_with_set(session):
    """Returns (session, live_set_id, [entry_id, entry_id, entry_id])."""
    s = session
    mr = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path="/srv/test-media")
    s.add(mr)
    await s.flush()
    user = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test",
                username=f"u{uuid.uuid4().hex[:6]}",
                display_name="u", password_hash=hash_password("aaaaaaaa"))
    s.add(user)
    await s.flush()
    live = LiveSet(slug=f"s-{uuid.uuid4().hex[:6]}", title="t",
                   media_root_id=mr.id, audio_path="x/y.flac",
                   status="published", source_type="upload", uploaded_by=user.id)
    s.add(live)
    await s.flush()
    entry_ids = []
    for i, sec in enumerate([0, 60, 120]):
        e = TracklistEntry(live_set_id=live.id, position=i,
                           start_seconds=sec, raw_label=f"e{i}",
                           created_by=user.id)
        s.add(e)
        await s.flush()
        entry_ids.append(str(e.id))
    await s.commit()
    yield s, live.id, entry_ids


@pytest.fixture(autouse=True)
async def _cleanup_catalog_rows():
    """Delete LiveSet + MediaRoot + test User rows so leftover rows don't accumulate.

    LiveSet.media_root_id and LiveSet.uploaded_by have ON DELETE RESTRICT, so
    LiveSet rows must be cleared first. Test-created Users use the *@x.test
    email pattern (see test_probe.py); the seeded admin (apps/web) lives at
    admin@example.test and is unaffected.

    Kept decoupled from the web app conftest — packages/core tests must not
    depend on apps/web fixtures.
    """
    init_engine(os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault",
    ))
    async with session_factory()() as s:
        await s.execute(delete(LiveSet))
        await s.execute(delete(MediaRoot))
        await s.execute(delete(User).where(User.email.like("%@x.test")))
        await s.commit()
    yield
    async with session_factory()() as s:
        await s.execute(delete(LiveSet))
        await s.execute(delete(MediaRoot))
        await s.execute(delete(User).where(User.email.like("%@x.test")))
        await s.commit()


@pytest.fixture(autouse=True)
async def _cleanup_ingest_source_state():
    """Delete ingest_source_state rows BEFORE each test so a committed row left
    behind by a prior web admin source-toggle test (or a prior run) can't make
    the ingest-source service tests non-deterministic.

    Uses its own committing session (NOT the rollback ``session`` fixture) so a
    stale committed row is actually removed. Cleans before and after to keep
    reruns idempotent. Decoupled from apps/web — core tests must not depend on
    web fixtures.
    """
    init_engine(os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault",
    ))
    async with session_factory()() as s:
        await s.execute(delete(IngestSourceState))
        await s.commit()
    yield
    async with session_factory()() as s:
        await s.execute(delete(IngestSourceState))
        await s.commit()


@pytest.fixture(autouse=True)
async def _cleanup_monitors():
    """Delete MonitorDiscovery + Monitor rows so monitor tests can rerun.

    MonitorDiscovery.monitor_id has ondelete=CASCADE, but discoveries are
    cleared first explicitly anyway. The monitor / monitor_discovery tables
    don't exist until the Phase 7C migration (Task 3) is applied; until then
    the delete raises a missing-table error, which we tolerate.
    """
    init_engine(os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault",
    ))
    async with session_factory()() as s:
        try:
            await s.execute(delete(MonitorDiscovery))
            await s.execute(delete(Monitor))
            await s.commit()
        except ProgrammingError:
            await s.rollback()  # 7C: tolerate pre-migration absence
    yield
    async with session_factory()() as s:
        try:
            await s.execute(delete(MonitorDiscovery))
            await s.execute(delete(Monitor))
            await s.commit()
        except ProgrammingError:
            await s.rollback()  # 7C: tolerate pre-migration absence

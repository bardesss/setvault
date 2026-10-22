import asyncio
import os

import pytest
from setvault_core.models.identity import User
from setvault_core.models.system import Job
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# Every rq id a worker test uses starts with this, so cleanup never touches
# real rows; test users use the @wtest.test domain for the same reason.
RQ_PREFIX = "wtest-"


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


async def _cleanup(conn):
    await conn.execute(delete(Job).where(Job.rq_id.like(f"{RQ_PREFIX}%")))
    await conn.execute(delete(User).where(User.email.like("%@wtest.test")))


@pytest.fixture
def run_db(db_url):
    """``run_db(fn)`` runs ``await fn(conn)`` on a throwaway engine (the tests
    are sync, like the RQ hooks) and returns its result. Requesting it also
    clears the test rows before and after the test; pure helper tests that
    don't request it run without a database."""
    def _run(fn):
        async def _main():
            engine = create_async_engine(db_url, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    return await fn(conn)
            finally:
                await engine.dispose()
        return asyncio.run(_main())
    _run(_cleanup)
    yield _run
    _run(_cleanup)

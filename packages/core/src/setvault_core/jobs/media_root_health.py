from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.email import DATABASE_URL_ENV
from setvault_core.models.catalog import MediaRoot
from setvault_core.services.storage import probe


async def run_health_checks() -> None:
    async with session_factory()() as s:
        for row in (await s.execute(select(MediaRoot))).scalars():
            row.last_health_status = probe(row.host_path)
            row.last_health_check_at = datetime.now(UTC)
        await s.commit()


def run_health_checks_sync() -> None:
    """RQ-callable wrapper. Re-initialises the engine from env vars."""
    if DATABASE_URL_ENV in os.environ:
        init_engine(os.environ[DATABASE_URL_ENV])
    run_job(run_health_checks())

"""Daily scheduled job that deletes ``AuditEvent`` rows older than the
admin-configured retention window (§J17).

Reads ``SystemConfig.audit_retention_days`` (default 90). A value of 0 or
negative disables pruning — useful for compliance setups that want to keep
the audit log forever and rely on filesystem-level archival.

Also deletes ``Job`` run records (Admin -> Jobs) older than
``JOB_RETENTION_DAYS``, independent of the audit setting.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.system import AuditEvent, Job
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)

JOB_RETENTION_DAYS = 30


async def _prune_jobs(s) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=JOB_RETENTION_DAYS)
    result = await s.execute(delete(Job).where(Job.created_at < cutoff))
    await s.commit()
    deleted = result.rowcount or 0
    if deleted:
        logger.info("audit_retention: pruned %d job runs older than %d days",
                    deleted, JOB_RETENTION_DAYS)
    return deleted


async def prune_audit_events() -> dict:
    """Returns ``{"deleted": N, "retention_days": N, "jobs_deleted": N}``."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        jobs_deleted = await _prune_jobs(s)
        config = await get_config(s)
        days = config.audit_retention_days
        if days <= 0:
            return {"deleted": 0, "retention_days": days, "jobs_deleted": jobs_deleted}

        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await s.execute(
            delete(AuditEvent).where(AuditEvent.created_at < cutoff)
        )
        await s.commit()
        deleted = result.rowcount or 0
        if deleted:
            logger.info(
                "audit_retention: pruned %d events older than %d days",
                deleted, days,
            )
        return {"deleted": deleted, "retention_days": days,
                "jobs_deleted": jobs_deleted}


def run_prune_audit_events() -> dict:
    """RQ entry point."""
    return run_job(prune_audit_events())

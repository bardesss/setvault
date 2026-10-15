"""Daily scheduled job that deletes ``AuditEvent`` rows older than the
admin-configured retention window (§J17).

Reads ``SystemConfig.audit_retention_days`` (default 90). A value of 0 or
negative disables pruning — useful for compliance setups that want to keep
the audit log forever and rely on filesystem-level archival.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.system import AuditEvent
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)


async def prune_audit_events() -> dict:
    """Returns ``{"deleted": N, "retention_days": N}``."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        config = await get_config(s)
        days = config.audit_retention_days
        if days <= 0:
            return {"deleted": 0, "retention_days": days}

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
        return {"deleted": deleted, "retention_days": days}


def run_prune_audit_events() -> dict:
    """RQ entry point."""
    return run_job(prune_audit_events())

"""Reset the recycle-bin purge grace window to 14 days from now

The periodic recycle-bin purge job never ran before the scheduler service was
added, so soft-deleted sets older than their grace window piled up. Give
everything currently in the bin a fresh 14-day window so enabling the
scheduler does not instantly delete it. Windows that already end later are kept.

Revision ID: 0027_purge_grace_reset
Revises: 0026_7d_backfill_failed
Create Date: 2026-10-19 12:00:00
"""
from alembic import op

revision = "0027_purge_grace_reset"
down_revision = "0026_7d_backfill_failed"
branch_labels = None
depends_on = None

PURGE_GRACE_RESET_SQL = (
    "UPDATE live_sets "
    "SET purge_after_at = GREATEST(COALESCE(purge_after_at, now()), now() + interval '14 days') "
    "WHERE deleted_at IS NOT NULL"
)


def upgrade() -> None:
    op.execute(PURGE_GRACE_RESET_SQL)


def downgrade() -> None:
    # Data-only change; the previous per-row windows are not recoverable and
    # restoring shorter ones would only make rows purge sooner. No-op.
    pass

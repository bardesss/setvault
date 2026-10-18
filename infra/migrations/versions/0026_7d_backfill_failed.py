"""live_sets.quality_backfill_failed_at: sets the quality backfill gave up on

Revision ID: 0026_7d_backfill_failed
Revises: 0025_7d_match_offset
Create Date: 2026-10-19 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0026_7d_backfill_failed"
down_revision = "0025_7d_match_offset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_sets",
        sa.Column("quality_backfill_failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("live_sets", "quality_backfill_failed_at")

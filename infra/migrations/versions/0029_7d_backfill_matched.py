"""live_sets.backfill_matched_at: published sets the backfill matched but left unmerged

Revision ID: 0029_7d_backfill_matched
Revises: 0028_7d_upgrades
Create Date: 2026-10-19 14:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0029_7d_backfill_matched"
down_revision = "0028_7d_upgrades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_sets",
        sa.Column("backfill_matched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("live_sets", "backfill_matched_at")

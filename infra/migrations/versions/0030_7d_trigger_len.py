"""set_upgrade_events.trigger: String(16) -> String(32)

Revision ID: 0030_7d_trigger_len
Revises: 0029_7d_backfill_matched
Create Date: 2026-10-19 18:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0030_7d_trigger_len"
down_revision = "0029_7d_backfill_matched"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "set_upgrade_events", "trigger",
        type_=sa.String(32), existing_type=sa.String(16), existing_nullable=False,
    )


def downgrade() -> None:
    # Values longer than 16 characters are cut so the column can shrink.
    op.execute(
        "UPDATE set_upgrade_events SET trigger = left(trigger, 16) "
        "WHERE length(trigger) > 16"
    )
    op.alter_column(
        "set_upgrade_events", "trigger",
        type_=sa.String(16), existing_type=sa.String(32), existing_nullable=False,
    )

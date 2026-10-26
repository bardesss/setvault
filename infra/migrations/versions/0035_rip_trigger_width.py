"""P3: rip_jobs.trigger as wide as set_upgrade_events.trigger

Revision ID: 0035_rip_trigger_width
Revises: 0034_set_sizes
Create Date: 2026-10-25 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0035_rip_trigger_width"
down_revision = "0034_set_sizes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "rip_jobs", "trigger",
        existing_type=sa.String(16), type_=sa.String(32), existing_nullable=True,
    )


def downgrade() -> None:
    # Fails if a stored trigger is longer than 16 characters; none of the
    # current values is.
    op.alter_column(
        "rip_jobs", "trigger",
        existing_type=sa.String(32), type_=sa.String(16), existing_nullable=True,
    )

"""system_config quality profile + upgrade settings

Revision ID: 0023_7d_quality_profile
Revises: 0022_7d_set_quality
Create Date: 2026-10-18 15:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_7d_quality_profile"
down_revision = "0022_7d_set_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_config", sa.Column(
        "quality_tiers_order", postgresql.JSONB(), nullable=False,
        server_default=sa.text(
            """'["lossless","high","good","ok","low"]'::jsonb"""
        ),
    ))
    op.add_column("system_config", sa.Column(
        "quality_cutoff", sa.String(16), nullable=False, server_default="lossless",
    ))
    op.add_column("system_config", sa.Column(
        "auto_upgrades_enabled", sa.Boolean(), nullable=False,
        server_default=sa.true(),
    ))
    op.add_column("system_config", sa.Column(
        "upgrade_search_schedule", sa.String(8), nullable=False,
        server_default="weekly",
    ))


def downgrade() -> None:
    op.drop_column("system_config", "upgrade_search_schedule")
    op.drop_column("system_config", "auto_upgrades_enabled")
    op.drop_column("system_config", "quality_cutoff")
    op.drop_column("system_config", "quality_tiers_order")

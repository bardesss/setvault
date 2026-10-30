"""Admin toggle for the 1001tracklists tracklist import

Revision ID: 0038_admin_1001tl_toggle
Revises: 0037_playlists_and_queue
Create Date: 2026-10-30 08:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0038_admin_1001tl_toggle"
down_revision = "0037_playlists_and_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_config",
        sa.Column(
            "allow_1001tl_scrape", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("system_config", "allow_1001tl_scrape")

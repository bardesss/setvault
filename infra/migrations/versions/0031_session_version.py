"""users.session_version: bumped to revoke every outstanding session cookie

Revision ID: 0031_session_version
Revises: 0030_7d_trigger_len
Create Date: 2026-10-21 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0031_session_version"
down_revision = "0030_7d_trigger_len"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "session_version")

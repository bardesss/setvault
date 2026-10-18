"""live_sets.match_offset_seconds: where a duplicate's audio starts in its original

Revision ID: 0025_7d_match_offset
Revises: 0024_7d_raw_fingerprint
Create Date: 2026-10-18 17:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_7d_match_offset"
down_revision = "0024_7d_raw_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("live_sets", sa.Column("match_offset_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("live_sets", "match_offset_seconds")

"""P2b: set file sizes (original and stream) for the storage totals

Revision ID: 0034_set_sizes
Revises: 0033_p2a
Create Date: 2026-10-24 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0034_set_sizes"
down_revision = "0033_p2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL until measured; jobs/size_backfill.py fills existing sets.
    op.add_column("live_sets", sa.Column("audio_bytes", sa.BigInteger(), nullable=True))
    op.add_column("live_sets", sa.Column("stream_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("live_sets", "stream_bytes")
    op.drop_column("live_sets", "audio_bytes")

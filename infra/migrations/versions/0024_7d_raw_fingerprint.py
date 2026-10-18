"""set_fingerprints raw chromaprint for fuzzy matching

Revision ID: 0024_7d_raw_fingerprint
Revises: 0023_7d_quality_profile
Create Date: 2026-10-18 16:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0024_7d_raw_fingerprint"
down_revision = "0023_7d_quality_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("set_fingerprints", sa.Column("raw", sa.LargeBinary(), nullable=True))
    op.add_column("set_fingerprints", sa.Column("raw_version", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("set_fingerprints", "raw_version")
    op.drop_column("set_fingerprints", "raw")

# infra/migrations/versions/0022_7d_set_quality.py
"""live_sets audio quality columns + upgrade bookkeeping

Revision ID: 0022_7d_set_quality
Revises: 0021_watch_folder_heartbeat
Create Date: 2026-10-18 14:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0022_7d_set_quality"
down_revision = "0021_watch_folder_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("live_sets", sa.Column("audio_codec", sa.String(32), nullable=True))
    op.add_column("live_sets", sa.Column("audio_bitrate_kbps", sa.Integer(), nullable=True))
    op.add_column("live_sets", sa.Column("audio_sample_rate", sa.Integer(), nullable=True))
    op.add_column("live_sets", sa.Column("audio_bit_depth", sa.Integer(), nullable=True))
    op.add_column("live_sets", sa.Column("audio_lossless", sa.Boolean(), nullable=True))
    op.add_column("live_sets", sa.Column("quality_tier", sa.String(16), nullable=True))
    op.add_column("live_sets", sa.Column(
        "quality_measured_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("live_sets", sa.Column(
        "upgrades_enabled", sa.Boolean(), nullable=False, server_default=sa.true(),
    ))
    op.add_column("live_sets", sa.Column(
        "last_upgrade_search_at", sa.DateTime(timezone=True), nullable=True,
    ))


def downgrade() -> None:
    for col in ("last_upgrade_search_at", "upgrades_enabled", "quality_measured_at",
                "quality_tier", "audio_lossless", "audio_bit_depth",
                "audio_sample_rate", "audio_bitrate_kbps", "audio_codec"):
        op.drop_column("live_sets", col)

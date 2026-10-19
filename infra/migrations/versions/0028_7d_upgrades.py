"""set_upgrade_events, rip_jobs upgrade targeting, live_sets.duplicate_kept_at

Revision ID: 0028_7d_upgrades
Revises: 0027_purge_grace_reset
Create Date: 2026-10-19 11:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_7d_upgrades"
down_revision = "0027_purge_grace_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "set_upgrade_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "live_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("live_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("from_tier", sa.String(16), nullable=True),
        sa.Column("from_codec", sa.String(32), nullable=True),
        sa.Column("from_bitrate_kbps", sa.Integer, nullable=True),
        sa.Column("from_source_type", sa.String(32), nullable=True),
        sa.Column("from_source_url", sa.String(2048), nullable=True),
        sa.Column("to_tier", sa.String(16), nullable=True),
        sa.Column("to_codec", sa.String(32), nullable=True),
        sa.Column("to_bitrate_kbps", sa.Integer, nullable=True),
        sa.Column("to_source_type", sa.String(32), nullable=True),
        sa.Column("to_source_url", sa.String(2048), nullable=True),
        sa.Column("candidate_source_kind", sa.String(32), nullable=True),
        sa.Column("candidate_external_id", sa.String(255), nullable=True),
        sa.Column("offset_seconds", sa.Float, nullable=True),
    )
    op.create_index(
        "ix_set_upgrade_events_live_set_id", "set_upgrade_events", ["live_set_id"]
    )
    op.add_column(
        "rip_jobs",
        sa.Column(
            "upgrade_target_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("live_sets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # The upgrade search and rip dedup look rips up by their target set.
    op.create_index(
        "ix_rip_jobs_upgrade_target_set_id", "rip_jobs", ["upgrade_target_set_id"]
    )
    op.add_column("rip_jobs", sa.Column("trigger", sa.String(16), nullable=True))
    op.add_column(
        "live_sets",
        sa.Column("duplicate_kept_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("live_sets", "duplicate_kept_at")
    op.drop_column("rip_jobs", "trigger")
    op.drop_index("ix_rip_jobs_upgrade_target_set_id", table_name="rip_jobs")
    op.drop_column("rip_jobs", "upgrade_target_set_id")
    op.drop_index("ix_set_upgrade_events_live_set_id", table_name="set_upgrade_events")
    op.drop_table("set_upgrade_events")

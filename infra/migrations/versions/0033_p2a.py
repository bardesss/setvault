"""P2a: monitor catalog link, loudness target, backup settings, stream gain

Revision ID: 0033_p2a
Revises: 0032_jobs_per_run
Create Date: 2026-10-23 12:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_p2a"
down_revision = "0032_jobs_per_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitor", sa.Column("catalog_kind", sa.String(length=16), nullable=True))
    op.add_column(
        "monitor", sa.Column("catalog_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_monitors_catalog", "monitor", ["catalog_kind", "catalog_id"])

    op.add_column(
        "system_config",
        sa.Column(
            "loudness_target_lufs", sa.Float(), nullable=True, server_default=sa.text("-14.0")
        ),
    )
    op.add_column(
        "system_config",
        sa.Column("backup_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "system_config",
        sa.Column("backup_time", sa.String(length=5), nullable=False, server_default="03:30"),
    )
    op.add_column(
        "system_config",
        sa.Column("backup_keep", sa.Integer(), nullable=False, server_default=sa.text("14")),
    )
    op.add_column(
        "system_config", sa.Column("backup_dir", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "system_config",
        sa.Column("last_backup_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "system_config", sa.Column("last_backup_status", sa.String(length=16), nullable=True)
    )
    op.add_column("system_config", sa.Column("last_backup_error", sa.Text(), nullable=True))
    op.add_column(
        "system_config", sa.Column("last_backup_bytes", sa.BigInteger(), nullable=True)
    )

    op.add_column("live_sets", sa.Column("stream_gain_db", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("live_sets", "stream_gain_db")

    for col in (
        "last_backup_bytes",
        "last_backup_error",
        "last_backup_status",
        "last_backup_at",
        "backup_dir",
        "backup_keep",
        "backup_time",
        "backup_enabled",
        "loudness_target_lufs",
    ):
        op.drop_column("system_config", col)

    op.drop_index("ix_monitors_catalog", table_name="monitor")
    op.drop_column("monitor", "catalog_id")
    op.drop_column("monitor", "catalog_kind")

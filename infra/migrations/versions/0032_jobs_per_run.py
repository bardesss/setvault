"""jobs: one row per run. id becomes a generated UUID; the RQ id moves to rq_id

RQ reuses ids (rq-scheduler re-enqueues periodic jobs under the same id;
monitor polls and upgrade-search-now use fixed ids), so the RQ id can't be the
primary key of a per-run history.

Revision ID: 0032_jobs_per_run
Revises: 0031_session_version
Create Date: 2026-10-22 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0032_jobs_per_run"
down_revision = "0031_session_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("rq_id", sa.String(length=64), nullable=True))
    op.execute("UPDATE jobs SET rq_id = id")
    op.alter_column("jobs", "rq_id", nullable=False)
    op.create_index(op.f("ix_jobs_rq_id"), "jobs", ["rq_id"], unique=False)
    op.alter_column("jobs", "id", server_default=sa.text("gen_random_uuid()::text"))


def downgrade() -> None:
    op.alter_column("jobs", "id", server_default=None)
    op.drop_index(op.f("ix_jobs_rq_id"), table_name="jobs")
    op.drop_column("jobs", "rq_id")

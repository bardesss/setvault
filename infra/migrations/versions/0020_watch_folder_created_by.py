# infra/migrations/versions/0020_watch_folder_created_by.py
"""watch_folders.created_by — attribute watch-folder ingests to the folder's creator

Revision ID: 0020_watch_folder_created_by
Revises: 0019_catalog_merge_columns
Create Date: 2026-10-15 15:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0020_watch_folder_created_by"
down_revision = "0019_catalog_merge_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: folders created before this column fall back to the first
    # admin at ingest time, as before.
    op.add_column("watch_folders", sa.Column(
        "created_by", UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("watch_folders", "created_by")

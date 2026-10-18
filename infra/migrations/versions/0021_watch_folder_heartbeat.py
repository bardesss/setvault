# infra/migrations/versions/0021_watch_folder_heartbeat.py
"""watch_folders.last_watched_at — watcher heartbeat for catch-up scans

Revision ID: 0021_watch_folder_heartbeat
Revises: 0020_watch_folder_created_by
Create Date: 2026-10-18 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_watch_folder_heartbeat"
down_revision = "0020_watch_folder_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("watch_folders", sa.Column(
        "last_watched_at", sa.DateTime(timezone=True), nullable=True,
    ))
    # Existing folders count as watched up to now, so the first catch-up scan
    # after upgrading only picks up new arrivals instead of re-importing the
    # folder's whole back catalogue. NULL is reserved for folders added later,
    # which get a full initial import.
    op.execute("UPDATE watch_folders SET last_watched_at = now()")


def downgrade() -> None:
    op.drop_column("watch_folders", "last_watched_at")

"""P4b: playlists, playlist items and the synced play queue

Revision ID: 0037_playlists_and_queue
Revises: 0036_webhook_hardening
Create Date: 2026-10-27 15:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037_playlists_and_queue"
down_revision = "0036_webhook_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_playlists_owner_user_id", "playlists", ["owner_user_id"])
    op.create_table(
        "playlist_items",
        sa.Column("playlist_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("live_set_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("live_sets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_playlist_items_live_set_id", "playlist_items", ["live_set_id"])
    op.create_table(
        "play_queues",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("set_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
                  server_default=sa.text("'{}'"), nullable=False),
        sa.Column("current_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("play_queues")
    op.drop_index("ix_playlist_items_live_set_id", table_name="playlist_items")
    op.drop_table("playlist_items")
    op.drop_index("ix_playlists_owner_user_id", table_name="playlists")
    op.drop_table("playlists")
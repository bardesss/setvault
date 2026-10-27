"""P4a: encrypted webhook headers and secrets, delivery log table

Revision ID: 0036_webhook_hardening
Revises: 0035_rip_trigger_width
Create Date: 2026-10-27 12:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_webhook_hardening"
down_revision = "0035_rip_trigger_width"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("library_webhooks", sa.Column("encrypted_headers", sa.LargeBinary(), nullable=True))
    op.add_column("library_webhooks", sa.Column("encrypted_secret", sa.LargeBinary(), nullable=True))
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("webhook_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("library_webhooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delivery_id", sa.String(36), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_webhook_deliveries_webhook_id", "webhook_deliveries", ["webhook_id"])
    op.create_index("ix_webhook_deliveries_webhook_created", "webhook_deliveries",
                    ["webhook_id", "created_at"])


def downgrade() -> None:
    """Drops the delivery log and both columns. Encrypted headers and signing
    secrets are lost: headers already moved out of the plaintext column are not
    restored."""
    op.drop_index("ix_webhook_deliveries_webhook_created", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_webhook_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_column("library_webhooks", "encrypted_secret")
    op.drop_column("library_webhooks", "encrypted_headers")

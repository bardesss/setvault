from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from setvault_core.models.base import Base, UuidPkMixin


class LibraryWebhook(Base, UuidPkMixin):
    __tablename__ = "library_webhooks"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    body_template: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Legacy plaintext headers; emptied ({}) once moved into encrypted_headers.
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    encrypted_headers: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_call_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WebhookDelivery(Base, UuidPkMixin):
    """One delivery attempt of a webhook (newest 50 per webhook are kept)."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_deliveries_webhook_created", "webhook_id", "created_at"),)

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("library_webhooks.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    delivery_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

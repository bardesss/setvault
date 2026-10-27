"""Webhook secrets, encrypted headers and request signing."""
from __future__ import annotations

import hmac
import json
import secrets
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.library_webhook import LibraryWebhook
from setvault_core.services.crypto import Crypter

KNOWN_EVENTS: tuple[str, ...] = (
    "set.published", "set.updated", "set.deleted", "set.restored", "set.purged",
)


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def set_secret(row: LibraryWebhook, secret: str, crypter: Crypter) -> None:
    row.encrypted_secret = crypter.encrypt(secret.encode("utf-8"))


def get_secret(row: LibraryWebhook, crypter: Crypter) -> str | None:
    if row.encrypted_secret is None:
        return None
    return crypter.decrypt(row.encrypted_secret).decode("utf-8")


def set_headers(row: LibraryWebhook, headers: dict[str, str], crypter: Crypter) -> None:
    """Store headers encrypted and clear the legacy plaintext column."""
    row.encrypted_headers = (
        crypter.encrypt(json.dumps(headers).encode("utf-8")) if headers else None
    )
    row.headers = {}


def get_headers(row: LibraryWebhook, crypter: Crypter) -> dict[str, str]:
    """Decrypted headers; falls back to the legacy plaintext column until the
    worker has migrated the row."""
    if row.encrypted_headers is not None:
        return json.loads(crypter.decrypt(row.encrypted_headers).decode("utf-8"))
    return dict(row.headers or {})


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, sha256)
    return "sha256=" + mac.hexdigest()


async def migrate_plaintext_headers(session: AsyncSession, crypter: Crypter) -> int:
    """Encrypt every row that still holds plaintext headers. Idempotent; the
    caller commits."""
    rows = (await session.execute(
        select(LibraryWebhook)
        .where(LibraryWebhook.encrypted_headers.is_(None), LibraryWebhook.headers != {})
        .with_for_update()
    )).scalars().all()
    changed = 0
    for row in rows:
        if row.headers:
            set_headers(row, dict(row.headers), crypter)
            changed += 1
    return changed

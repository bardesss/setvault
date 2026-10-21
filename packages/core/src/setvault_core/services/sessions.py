from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from itsdangerous import BadSignature, TimestampSigner

SESSION_COOKIE = "session"
SESSION_TTL = timedelta(days=30)


@dataclass(frozen=True)
class SessionData:
    user_id: str
    version: int


class SessionSigner:
    def __init__(self, secret_key: str) -> None:
        self._signer = TimestampSigner(secret_key, salt="setvault.session")

    def issue(self, user_id: str, version: int) -> str:
        nonce = secrets.token_urlsafe(16)
        payload = f"{user_id}:{version}:{nonce}"
        return self._signer.sign(payload).decode("ascii")

    def read(self, raw: str) -> SessionData | None:
        try:
            value = self._signer.unsign(
                raw, max_age=int(SESSION_TTL.total_seconds()),
            ).decode("ascii")
        except BadSignature:
            return None
        return _parse_payload(value)


def _parse_payload(value: str) -> SessionData | None:
    """``user_id:nonce`` (legacy, version 0) or ``user_id:version:nonce``.

    The nonce comes from ``token_urlsafe`` and never contains ``:``, so any
    other shape is malformed and rejected rather than guessed at.
    """
    parts = value.split(":")
    if len(parts) == 2:
        user_id, nonce = parts
        version = 0
    elif len(parts) == 3:
        user_id, raw_version, nonce = parts
        if not (raw_version.isascii() and raw_version.isdigit()):
            return None
        version = int(raw_version)
    else:
        return None
    if not user_id or not nonce:
        return None
    return SessionData(user_id=user_id, version=version)

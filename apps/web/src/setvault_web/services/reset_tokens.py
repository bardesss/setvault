from __future__ import annotations

from setvault_core.models.identity import EmailToken, User
from setvault_core.services.tokens import expires, generate_token
from sqlalchemy.ext.asyncio import AsyncSession

RESET_TOKEN_HOURS = 1


def mint_reset_token(session: AsyncSession, user: User) -> tuple[str, EmailToken]:
    """Add a 1 h password-reset token for ``user`` and revoke their sessions.

    Returns ``(plaintext, token_row)``; only the hash is stored. The caller commits.
    """
    plaintext, digest = generate_token()
    token = EmailToken(user_id=user.id, email=user.email, kind="password_reset",
                       token_hash=digest, payload={},
                       expires_at=expires(RESET_TOKEN_HOURS))
    session.add(token)
    user.session_version += 1
    return plaintext, token

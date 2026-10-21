"""Safe first-admin bootstrap CLI.

Run as ``python -m setvault_web.create_admin`` to create (or promote) an admin
user without exposing any dev-only seed endpoint. Configuration is read from the
environment so the password never appears on the command line or in the output:

- ``ADMIN_EMAIL`` (required)
- ``ADMIN_PASSWORD`` (required, minimum 12 characters)
- ``ADMIN_USERNAME`` (optional, defaults to the email local-part)
- ``ADMIN_DISPLAY_NAME`` (optional, defaults to the username)

Behaviour is idempotent: if a user with the given email already exists and is an
admin, nothing changes; if they exist but are not an admin, they are promoted;
otherwise a fresh verified admin is created. The password is never printed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime

from setvault_core.db import init_engine, session_factory
from setvault_core.models.identity import User
from setvault_core.services.password_policy import MIN_PASSWORD_LENGTH
from setvault_core.services.passwords import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import get_settings


class CreateAdminError(Exception):
    """Raised for invalid input (missing/short credentials)."""


async def create_or_promote_admin(
    session: AsyncSession,
    email: str,
    password: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
) -> tuple[User, str]:
    """Create a new admin, promote an existing user, or no-op if already admin.

    Returns ``(user, action)`` where ``action`` is one of ``"created"``,
    ``"promoted"`` or ``"exists"``. Raises :class:`CreateAdminError` on invalid
    input. Commits the session when it makes a change.
    """
    email = (email or "").strip()
    if not email:
        raise CreateAdminError("ADMIN_EMAIL is required")
    if not password:
        raise CreateAdminError("ADMIN_PASSWORD is required")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CreateAdminError(
            f"ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters"
        )

    resolved_username = (username or "").strip() or email.split("@", 1)[0]
    resolved_display = (display_name or "").strip() or resolved_username

    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing is not None:
        if existing.role == "admin":
            return existing, "exists"
        existing.role = "admin"
        await session.commit()
        return existing, "promoted"

    user = User(
        email=email,
        username=resolved_username,
        display_name=resolved_display,
        password_hash=hash_password(password),
        role="admin",
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.commit()
    return user, "created"


async def _run() -> int:
    email = os.environ.get("ADMIN_EMAIL", "")
    password = os.environ.get("ADMIN_PASSWORD", "")
    username = os.environ.get("ADMIN_USERNAME")
    display_name = os.environ.get("ADMIN_DISPLAY_NAME")

    init_engine(get_settings().database_url)
    async with session_factory()() as session:
        user, action = await create_or_promote_admin(
            session,
            email,
            password,
            username=username,
            display_name=display_name,
        )

    if action == "exists":
        print(f"admin already exists: {user.email}")
    elif action == "promoted":
        print(f"promoted existing user to admin: {user.email}")
    else:
        print(f"created admin: {user.email} (username: {user.username})")
    return 0


def main() -> None:
    try:
        rc = asyncio.run(_run())
    except CreateAdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(rc)


if __name__ == "__main__":
    main()

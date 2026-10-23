"""Password reset CLI for a locked-out admin.

Run as ``python -m setvault_web.reset_password``. Without ``--email`` it targets
the only admin (and refuses if there is more than one). Either:

- ``--link`` prints a one-hour reset URL (``{BASE_URL}/reset/{token}``), or
- the new password is read from the ``NEW_PASSWORD`` env var, falling back to an
  interactive prompt, so it never appears on the command line or in the output.

Either way existing sessions are revoked (``session_version`` is bumped) and a
``user.password_reset_cli`` audit event is written.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os

from setvault_core.db import init_engine, session_factory
from setvault_core.models.identity import User
from setvault_core.services.audit import log as audit_log
from setvault_core.services.password_policy import MIN_PASSWORD_LENGTH
from setvault_core.services.passwords import hash_password
from sqlalchemy import select

from setvault_web.config import get_settings
from setvault_web.services.reset_tokens import mint_reset_token


def pick_admin(admins: list[User]) -> User:
    """The sole admin, or exit when there is none or more than one."""
    if not admins:
        raise SystemExit("no admin exists; create one with python -m setvault_web.create_admin")
    if len(admins) > 1:
        raise SystemExit("more than one admin; pass --email")
    return admins[0]


async def reset_password(email: str | None, *, new_password: str | None, link: bool) -> str:
    """Reset (or mint a reset link for) one admin. Returns the line to print."""
    if not link:
        if not new_password:
            raise SystemExit("a new password is required (NEW_PASSWORD or the prompt)")
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise SystemExit(f"password must be at least {MIN_PASSWORD_LENGTH} characters")

    async with session_factory()() as session:
        if email:
            user = (await session.execute(
                select(User).where(User.email == email.strip())
            )).scalar_one_or_none()
            if user is None:
                raise SystemExit(f"no user with email {email}")
        else:
            admins = list((await session.execute(
                select(User).where(User.role == "admin")
            )).scalars())
            user = pick_admin(admins)

        if link:
            plaintext, _ = mint_reset_token(session, user)
            line = f"{get_settings().base_url}/reset/{plaintext}"
        else:
            user.password_hash = hash_password(new_password)
            user.session_version += 1
            line = f"password reset for {user.email}"
        await audit_log(
            session, actor_user_id=None, actor_kind="cli",
            action="user.password_reset_cli", target_type="User", target_id=str(user.id),
            after={"mode": "link" if link else "password"},
        )
        await session.commit()
    return line


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m setvault_web.reset_password",
        description="Reset the password of a locked-out admin.",
    )
    parser.add_argument("--email", help="user to reset (default: the only admin)")
    parser.add_argument("--link", action="store_true",
                        help="print a one-hour reset link instead of setting a password")
    args = parser.parse_args()

    new_password = None
    if not args.link:
        new_password = os.environ.get("NEW_PASSWORD") or getpass.getpass("New password: ")

    init_engine(get_settings().database_url)
    print(asyncio.run(reset_password(args.email, new_password=new_password, link=args.link)))


if __name__ == "__main__":
    main()

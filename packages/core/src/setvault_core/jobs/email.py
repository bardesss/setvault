from __future__ import annotations

import email.utils
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import TypedDict

logger = logging.getLogger(__name__)

# Env var names must match `setvault_web.config.Settings` field names (uppercased).
# Centralised here so a rename in setvault_web's Settings only needs the env-var
# constant in this module updated to match.
SECRET_KEY_ENV = "SECRET_KEY"  # noqa: S105 — env var name, not a secret value
DATABASE_URL_ENV = "DATABASE_URL"


class SmtpConfig(TypedDict):
    host: str
    port: int
    encryption: str  # "starttls" | "ssl" | "none"
    username: str | None
    password: str | None
    from_email: str
    from_name: str
    reply_to: str | None


def build_message(*, from_email: str, from_name: str, to: str, subject: str,
                  text: str, reply_to: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=from_email.split("@", 1)[1])
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    return msg


def send_email_sync(*, config: SmtpConfig, to: str, subject: str, text: str) -> None:
    msg = build_message(
        from_email=config["from_email"], from_name=config["from_name"],
        to=to, subject=subject, text=text, reply_to=config.get("reply_to"),
    )
    host, port = config["host"], int(config["port"])
    encryption = config["encryption"]
    timeout = 30
    if encryption == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=timeout,
                                  context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    try:
        client.ehlo()
        if encryption == "starttls":
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if config.get("username"):
            client.login(config["username"], config.get("password") or "")
        client.send_message(msg)
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            logger.debug("SMTP client.quit() raised on close", exc_info=True)


def send_email_job(*, connector_id: str, to: str, subject: str, text: str) -> None:
    """RQ entry point. Re-resolves config from DB + decrypts.

    Picks up Redis URL + DATABASE_URL from env (worker boot sets these)."""
    import json
    import os
    import uuid

    from setvault_core.db import init_engine, run_job, session_factory
    from setvault_core.models.system import NotificationConnector
    from setvault_core.services.crypto import Crypter

    async def _run() -> None:
        init_engine(os.environ[DATABASE_URL_ENV])
        async with session_factory()() as s:
            row = await s.get(NotificationConnector, uuid.UUID(connector_id))
            if row is None or not row.enabled or row.kind != "smtp":
                raise RuntimeError(f"connector {connector_id} unavailable")
            config = json.loads(
                Crypter(os.environ[SECRET_KEY_ENV]).decrypt(row.encrypted_config).decode("utf-8")
            )
        send_email_sync(config=config, to=to, subject=subject, text=text)

    run_job(_run())

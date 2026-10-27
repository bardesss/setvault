"""Worker job that fires a configured ``LibraryWebhook`` POST (§J15).

Triggered by the set fan-out (or the admin Test button) via RQ, which keeps the
slow outbound HTTP off the request thread. Every attempt is signed (when the
webhook has a secret), logged to ``webhook_deliveries`` and, on a retryable
outcome, retried by RQ on the ``RETRY_INTERVALS`` schedule.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime

import httpx
from rq import Queue, Retry, get_current_job
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.email import SECRET_KEY_ENV
from setvault_core.models.library_webhook import LibraryWebhook, WebhookDelivery
from setvault_core.services.crypto import Crypter
from setvault_core.services.webhook_security import get_headers, get_secret, sign

logger = logging.getLogger(__name__)

# Seconds before retry 1..5, so at most 6 attempts in total.
RETRY_INTERVALS: tuple[int, ...] = (60, 300, 1800, 7200, 21600)
KEEP_DELIVERIES = 50


class RetryableDeliveryError(Exception):
    """Raised after the attempt is logged, so RQ schedules the next retry."""


def is_retryable(status: int | None, error: str | None) -> bool:
    """Network errors, timeouts, 5xx, 408 and 429 are retried; any other
    non-2xx is permanent."""
    if status is None:
        return error is not None
    return status >= 500 or status in (408, 429)


async def dispatch_webhook(
    *,
    webhook_id: str,
    event: str,
    delivery_id: str,
    set_slug: str | None,
    set_id: str | None,
    title: str | None,
    attempt: int = 1,
) -> dict:
    """Look up the LibraryWebhook, render its body, sign and POST it, log the
    attempt. Raises ``RetryableDeliveryError`` (after committing the log row)
    when the outcome should be retried."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])
    crypter = Crypter(os.environ[SECRET_KEY_ENV])

    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(webhook_id))
        if row is None or not row.enabled:
            # Disabled or deleted (possibly mid-retry): stop quietly.
            return {"skipped": True, "reason": "not enabled or missing"}

        # Default body — used unless body_template is set on the row.
        body: dict = {
            "event": event,
            "set_slug": set_slug,
            "set_id": set_id,
            "title": title,
        }
        if row.body_template:
            # Template variables: {{event}}, {{slug}}, {{set_id}}, {{title}}.
            # Replace in any string value; leave other types as-is.
            def _render(val):
                if isinstance(val, str):
                    return (val
                        .replace("{{event}}", event or "")
                        .replace("{{slug}}", set_slug or "")
                        .replace("{{set_id}}", set_id or "")
                        .replace("{{title}}", title or ""))
                if isinstance(val, dict):
                    return {k: _render(v) for k, v in val.items()}
                if isinstance(val, list):
                    return [_render(v) for v in val]
                return val
            body = _render(row.body_template)

        # Serialise once: the signature and the request cover the same bytes.
        body_bytes = json.dumps(body, separators=(",", ":")).encode()
        timestamp = int(time.time())

        headers = {"Content-Type": "application/json"}
        headers.update({str(k): str(v) for k, v in get_headers(row, crypter).items()})
        headers["X-SetVault-Event"] = event
        headers["X-SetVault-Delivery"] = delivery_id
        headers["X-SetVault-Timestamp"] = str(timestamp)
        secret = get_secret(row, crypter)
        if secret is not None:
            headers["X-SetVault-Signature"] = sign(secret, timestamp, body_bytes)

        status: int | None = None
        error: str | None = None
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(row.target_url, content=body_bytes, headers=headers)
            status = resp.status_code
            if not 200 <= status < 300:
                error = f"HTTP {status}"
        except httpx.HTTPError as exc:
            error = (str(exc) or type(exc).__name__)[:500]
            logger.warning("webhook %s POST failed: %s", webhook_id, exc)
        duration_ms = int((time.monotonic() - started) * 1000)

        row.last_call_at = datetime.now(UTC)
        row.last_status_code = status
        row.last_error = error
        s.add(WebhookDelivery(
            webhook_id=row.id, delivery_id=delivery_id, event=event,
            attempt=attempt, status_code=status, error=error,
            duration_ms=duration_ms,
        ))
        try:
            await s.flush()
            keep = (select(WebhookDelivery.id)
                    .where(WebhookDelivery.webhook_id == row.id)
                    .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
                    .limit(KEEP_DELIVERIES))
            await s.execute(delete(WebhookDelivery).where(
                WebhookDelivery.webhook_id == row.id,
                WebhookDelivery.id.not_in(keep),
            ))
            await s.commit()
        except (IntegrityError, StaleDataError):
            # The webhook was deleted while the request was in flight.
            await s.rollback()
            return {"skipped": True, "reason": "deleted during delivery"}

    if is_retryable(status, error):
        raise RetryableDeliveryError(error or f"HTTP {status}")
    return {"status_code": status, "error": error}


def run_dispatch_webhook(
    *,
    webhook_id: str,
    event: str,
    delivery_id: str,
    set_slug: str | None = None,
    set_id: str | None = None,
    title: str | None = None,
) -> dict:
    """RQ entry point. The attempt number comes from the job's retry state."""
    job = get_current_job()
    left = getattr(job, "retries_left", None)
    attempt = 1 if left is None else 1 + (len(RETRY_INTERVALS) - left)
    return run_job(dispatch_webhook(
        webhook_id=webhook_id, event=event, delivery_id=delivery_id,
        set_slug=set_slug, set_id=set_id, title=title, attempt=attempt,
    ))


def enqueue_dispatch(
    queue: Queue,
    *,
    webhook_id: str,
    event: str,
    set_slug: str | None,
    set_id: str | None,
    title: str | None,
    retry: bool = True,
) -> str:
    """Enqueue one delivery and return its delivery id (stable across retries)."""
    delivery_id = str(uuid.uuid4())
    kwargs: dict = {}
    if retry:
        kwargs["retry"] = Retry(max=len(RETRY_INTERVALS), interval=list(RETRY_INTERVALS))
    queue.enqueue(
        "setvault_core.jobs.webhook_dispatch.run_dispatch_webhook",
        webhook_id=webhook_id, event=event, delivery_id=delivery_id,
        set_slug=set_slug, set_id=set_id, title=title,
        **kwargs,
    )
    return delivery_id

"""Worker job that fires a configured ``LibraryWebhook`` POST (§J15).

Triggered from the audit-log path (or any caller) via RQ — keeps the slow
outbound HTTP off the request thread. Failures are logged to the row's
``last_*`` columns but the job does not retry; the next event re-attempts.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

import httpx

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.library_webhook import LibraryWebhook

logger = logging.getLogger(__name__)


async def dispatch_webhook(
    *,
    webhook_id: str,
    event: str,
    set_slug: str | None,
    set_id: str | None,
    title: str | None,
) -> dict:
    """Look up the LibraryWebhook, render its body, POST. Update last_*."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        row = await s.get(LibraryWebhook, uuid.UUID(webhook_id))
        if row is None or not row.enabled:
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

        headers = {"Content-Type": "application/json"}
        if row.headers:
            headers.update({str(k): str(v) for k, v in row.headers.items()})

        status: int | None = None
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(row.target_url, json=body, headers=headers)
            status = resp.status_code
        except httpx.HTTPError as exc:
            error = str(exc)[:500]
            logger.warning("webhook %s POST failed: %s", row.id, exc)

        row.last_call_at = datetime.now(UTC)
        row.last_status_code = status
        row.last_error = error
        await s.commit()
        return {"status_code": status, "error": error}


def run_dispatch_webhook(
    *,
    webhook_id: str,
    event: str,
    set_slug: str | None = None,
    set_id: str | None = None,
    title: str | None = None,
) -> dict:
    return run_job(dispatch_webhook(
        webhook_id=webhook_id, event=event,
        set_slug=set_slug, set_id=set_id, title=title,
    ))

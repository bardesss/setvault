"""Daily scheduled job that polls GitHub's `releases/latest` endpoint and
caches the result on the SystemConfig singleton (§J16).

- Uses ``If-None-Match`` with the stored ETag so unchanged responses cost
  one HTTP round-trip and zero rate-limit budget.
- The repo to poll is read from the ``SETVAULT_RELEASES_REPO`` env var
  (e.g. ``Bardesss/setvault``); if not set, the job is a no-op so dev
  environments + forks don't accidentally hit the upstream.
- Network errors don't crash the worker — they update only
  ``latest_release_checked_at`` and log a warning.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import httpx

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)

USER_AGENT = "setvault-version-poll/1.0"


def _build_url(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}/releases/latest"


async def _fetch_latest(repo: str, etag: str | None) -> httpx.Response | None:
    """Single HTTP request with optional If-None-Match. Returns the response
    on success (including 304), None on transport error."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if etag:
        headers["If-None-Match"] = etag

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.get(_build_url(repo), headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("github_version_poll: network error: %s", exc)
        return None


async def poll_github_releases() -> dict:
    """Returns a summary dict.

    ``{"updated": bool, "etag_changed": bool, "version": str | None}``.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    summary: dict = {"updated": False, "etag_changed": False, "version": None}
    repo = os.environ.get("SETVAULT_RELEASES_REPO")
    if not repo:
        logger.debug("github_version_poll: SETVAULT_RELEASES_REPO not set, skipping")
        return summary

    async with session_factory()() as s:
        config = await get_config(s)
        prior_etag = config.latest_release_etag

        response = await _fetch_latest(repo, prior_etag)
        config.latest_release_checked_at = datetime.now(UTC)

        if response is None:
            await s.commit()
            return summary

        if response.status_code == 304:
            await s.commit()
            return summary  # nothing new

        if response.status_code != 200:
            logger.warning(
                "github_version_poll: %s returned %s",
                _build_url(repo), response.status_code,
            )
            await s.commit()
            return summary

        try:
            payload = response.json()
        except ValueError:
            logger.warning("github_version_poll: bad JSON")
            await s.commit()
            return summary

        new_version = payload.get("tag_name") or payload.get("name")
        new_url = payload.get("html_url")
        new_etag = response.headers.get("ETag")

        config.latest_release_version = new_version
        config.latest_release_url = new_url
        config.latest_release_etag = new_etag
        summary["updated"] = True
        summary["etag_changed"] = new_etag != prior_etag
        summary["version"] = new_version

        await s.commit()

    return summary


def run_poll_github_releases() -> dict:
    """RQ entry point."""
    return run_job(poll_github_releases())

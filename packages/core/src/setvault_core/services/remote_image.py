"""Fetching third-party images (platform thumbnails) server-side.

Shared by the web image proxy and the rip job's thumbnail download. Both
fetch URLs that ultimately come from a platform's metadata, so both refuse
hosts that resolve to private/loopback/link-local addresses.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

MAX_IMAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 10.0


class RemoteImageError(Exception):
    """The URL was refused, or the upstream didn't hand back a usable image."""


def is_blocked_host(host: str) -> bool:
    """True if ``host`` resolves to any private/loopback/link-local/reserved
    address. Unresolvable hosts are treated as blocked (fail closed)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return True
    return False


async def fetch_image(url: str) -> tuple[bytes, str]:
    """Download an external image; returns ``(body, content_type)``.

    Raises :class:`RemoteImageError` for a non-http(s) URL, a blocked host, a
    failed fetch, a non-image response or one over :data:`MAX_IMAGE_BYTES`.
    Redirects are not followed: a redirect could point at a blocked host.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RemoteImageError("unsupported image url")
    if is_blocked_host(parsed.hostname):
        raise RemoteImageError("blocked image host")
    try:
        async with (
            httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as cx,
            cx.stream("GET", url) as resp,
        ):
            ctype = resp.headers.get("content-type", "")
            if resp.status_code != 200 or not ctype.startswith("image/"):
                raise RemoteImageError("upstream is not an image")
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise RemoteImageError("image too large")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise RemoteImageError("upstream fetch failed") from exc
    return b"".join(chunks), ctype.split(";")[0].strip()

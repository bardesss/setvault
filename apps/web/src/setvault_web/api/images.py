"""Signed image proxy.

External search/discovery thumbnails (YouTube, SoundCloud, …) can't be loaded
directly: the strict CSP pins ``img-src 'self'``, and loading third-party images
in the browser would leak the user's IP/referrer to those platforms. So the
backend fetches them server-side and re-serves from this origin.

The target URL is HMAC-signed (see ``signed_urls.sign_image_url``) so this can
only ever fetch URLs *we* issued — it can't be turned into an open SSRF proxy.
A resolved-IP guard blocks private/loopback/link-local hosts as defence in depth.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from setvault_core.services.remote_image import MAX_IMAGE_BYTES as _MAX_BYTES
from setvault_core.services.remote_image import is_blocked_host as _is_blocked_host
from setvault_core.services.signed_urls import sign_image_url, verify_image_sig

from setvault_web.config import get_settings
from setvault_web.deps import current_user

router = APIRouter(prefix="/api/images", tags=["images"])

_TIMEOUT_SECONDS = 10.0


def build_proxied_image_url(url: str | None) -> str | None:
    """Same-origin, signed proxy URL for an external image — or ``None`` for a
    falsy input (so callers can map a missing thumbnail straight through)."""
    if not url:
        return None
    sig, exp = sign_image_url(secret_key=get_settings().secret_key, url=url)
    return f"/api/images/proxy?url={quote(url, safe='')}&exp={exp}&sig={sig}"


@router.get("/proxy")
async def proxy_image(
    url: Annotated[str, Query()],
    exp: Annotated[int, Query()],
    sig: Annotated[str, Query()],
    _: Annotated[object, Depends(current_user)],
) -> Response:
    settings = get_settings()
    if not verify_image_sig(secret_key=settings.secret_key, url=url, exp=exp, sig=sig):
        raise HTTPException(status_code=401, detail="invalid or expired image signature")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail="unsupported image url")
    if _is_blocked_host(parsed.hostname):
        raise HTTPException(status_code=400, detail="blocked image host")

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, follow_redirects=False
        ) as cx:
            resp = await cx.get(url)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="upstream fetch failed") from None

    ctype = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not ctype.startswith("image/"):
        raise HTTPException(status_code=502, detail="upstream is not an image")
    body = resp.content
    if len(body) > _MAX_BYTES:
        raise HTTPException(status_code=502, detail="image too large")

    return Response(
        content=body,
        media_type=ctype.split(";")[0].strip(),
        headers={"Cache-Control": "public, max-age=86400"},
    )

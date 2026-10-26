"""Pure-ASGI security-headers middleware.

Rewritten in Phase 5E away from ``starlette.middleware.base.BaseHTTPMiddleware``
for the same reason as the CSRF middleware: BaseHTTPMiddleware's inner anyio
task group leaks across pytest event loops and breaks the test harness even
though production paths work. The pure ASGI form has no inner task group.
"""
from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

# SvelteKit's adapter-static output bootstraps the app from an *inline*
# <script>. A strict `script-src 'self'` blocks inline scripts, so we hash
# those scripts at startup and add the digests to script-src — keeping the CSP
# strict (no 'unsafe-inline') while letting the real app hydrate. The hashes
# track whatever the build emitted, so they survive every frontend rebuild.
_INLINE_SCRIPT_RE = re.compile(rb"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def compute_inline_script_hashes(html: bytes) -> list[str]:
    """Return ``'sha256-…'`` CSP tokens for every inline <script> in ``html``.

    The digest is taken over the exact bytes between the tags — identical to
    what a browser hashes for CSP — so the result drops straight into
    ``script-src``. External scripts (``src=…``) are skipped; they're already
    covered by ``'self'``. Duplicate bodies collapse to one token.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for attrs, body in _INLINE_SCRIPT_RE.findall(html):
        if b"src=" in attrs.lower():
            continue
        token = "sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def _build_csp(frame_ancestors: str, script_hashes: Sequence[str]) -> str:
    script_src = "script-src 'self'"
    if script_hashes:
        script_src += " " + " ".join(f"'{h}'" for h in script_hashes)
    return (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "font-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        f"{script_src}; "
        "connect-src 'self' ws: wss:; "
        f"frame-ancestors {frame_ancestors}; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


_DEFAULTS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), usb=()"),
    (
        b"strict-transport-security",
        b"max-age=63072000; includeSubDomains; preload",
    ),
)


Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _is_embed_route(path: str) -> bool:
    """Routes that need third-party iframe embedding to work.

    Frontend page: ``/embed/<slug>``.
    Backend JSON used by that page: ``/api/sets/<slug>/embed``.
    """
    if path.startswith("/embed/") or path == "/embed":
        return True
    if path.startswith("/api/sets/") and path.endswith("/embed"):
        return True
    return False


def _setdefault(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> None:
    for existing_name, _ in headers:
        if existing_name == name:
            return
    headers.append((name, value))


class SecurityHeadersMiddleware:
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        script_hashes: Sequence[str] = (),
    ) -> None:
        self.app = app
        # Bake the inline-script hashes into both policies once at startup.
        self._default_csp = _build_csp("'none'", script_hashes).encode("latin-1")
        self._embed_csp = _build_csp("*", script_hashes).encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        embed = _is_embed_route(scope.get("path", "/"))
        csp = self._embed_csp if embed else self._default_csp

        async def send_wrapper(event: dict[str, Any]) -> None:
            if event["type"] == "http.response.start":
                headers = list(event.get("headers", []))
                _setdefault(headers, b"content-security-policy", csp)
                if not embed:
                    _setdefault(headers, b"x-frame-options", b"DENY")
                for name, value in _DEFAULTS:
                    _setdefault(headers, name, value)
                event = {**event, "headers": headers}
            await send(event)

        await self.app(scope, receive, send_wrapper)

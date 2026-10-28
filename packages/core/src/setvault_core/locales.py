"""UI languages the web app ships. The frontend keeps the same list in
`frontend/src/lib/i18n/locale.ts`; a vitest case checks the two match."""

from __future__ import annotations

SUPPORTED_LOCALES: tuple[str, ...] = ("en", "nl", "de", "es", "fr")

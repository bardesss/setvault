"""Naming template resolver for MediaRoot.naming_template (§J9).

Token vocabulary per master spec §J9:
    {Artist} {Party} {Series} {Venue} {Date} {Year} {Slug} {Type} {SetId} {Ext}

All tokens render as filesystem-safe slugs (alphanumerics + dashes); raw
catalog values containing slashes / colons / dots get normalised so the
result is safe to use as a path component. The literal `{Ext}` token is
ALWAYS the original extension including the leading dot (e.g. ``.opus``).

Missing values (no party, no venue, no date) fall back to the empty string
in the rendered path — leading to ``/.opus`` if the entire template was
optional tokens. Callers are expected to choose templates that always
contain a core required token like ``{SetId}`` or ``{Slug}``.

Backslashes are converted to forward slashes so the same template works on
Windows + Linux runners.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from setvault_core.models.catalog import LiveSet


_TOKEN_RE = re.compile(r"\{(?P<name>[A-Za-z]+)\}")

_UNIQUE_TOKENS = ("{SetId}", "{Slug}")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def validate_template(template: str) -> list[str]:
    """Problems with ``template`` as a naming template; empty when valid.

    Rejects unknown tokens, a template that doesn't end in ``{Ext}``, ``..``
    anywhere, and absolute paths (leading slash or backslash, or a drive
    letter). Token values can't escape the root (``_safe_segment``), so these
    checks on the literal text are enough.
    """
    errors: list[str] = []
    unknown = sorted({
        m.group("name") for m in _TOKEN_RE.finditer(template)
        if m.group("name") not in TOKENS
    })
    for name in unknown:
        errors.append(f"unknown token {{{name}}}")
    literal = _TOKEN_RE.sub("", template)
    if "{" in literal or "}" in literal:
        errors.append("unbalanced or malformed braces")
    if not template.endswith("{Ext}"):
        errors.append("template must end in {Ext}")
    if ".." in template:
        errors.append("template must not contain ..")
    if template.startswith(("/", "\\")) or _DRIVE_RE.match(template):
        errors.append("template must be a relative path")
    return errors


def template_has_unique_token(template: str) -> bool:
    """True when the template names each set uniquely ({SetId} or {Slug})."""
    return any(tok in template for tok in _UNIQUE_TOKENS)


# Characters not allowed in a single path segment. Slash also stripped from
# token VALUES so they can't escape a path component.
_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_segment(value: str) -> str:
    """Strip filesystem-unsafe characters; collapse runs of `-` and `.`;
    trim leading / trailing dashes and dots.

    Repeated dots are deliberately collapsed — `..` is a path-traversal
    sentinel that should never land in an auto-generated filename, even if
    the original artist/title legitimately contained ellipsis dots.
    """
    if not value:
        return ""
    out = _UNSAFE_CHARS_RE.sub("-", value).strip("-.")
    out = re.sub(r"-{2,}", "-", out)
    out = re.sub(r"\.{2,}", ".", out)
    return out


def _artist_name(live: LiveSet) -> str:
    """First credited artist's name, or empty if none yet attached."""
    artists = list(live.artists)
    if not artists:
        return ""
    # LiveSetArtist rows expose .artist (relationship loaded eagerly).
    first = artists[0]
    return getattr(first.artist, "name", "") or ""


# Token name → (live, ext) → safe-segment string. The single source of the
# token vocabulary: TOKENS (validation) is derived from it.
_RESOLVERS: dict[str, Callable[[LiveSet, str], str]] = {
    "Artist": lambda live, ext: _safe_segment(_artist_name(live)),
    "Party": lambda live, ext: _safe_segment(live.party.name if live.party else ""),
    "Series": lambda live, ext: _safe_segment(
        live.party.series.name if (live.party and live.party.series) else "",
    ),
    "Venue": lambda live, ext: _safe_segment(live.venue.name if live.venue else ""),
    "Date": lambda live, ext: live.date.isoformat() if live.date else "",
    "Year": lambda live, ext: str(live.date.year) if live.date else "",
    "Slug": lambda live, ext: _safe_segment(live.slug),
    "Type": lambda live, ext: _safe_segment(live.set_type or ""),
    "SetId": lambda live, ext: str(live.id),
    "Ext": lambda live, ext: ext,  # already includes the leading dot
}
TOKENS = frozenset(_RESOLVERS)


def _resolve_token(name: str, live: LiveSet, ext: str) -> str:
    """Token → safe-segment string. Unknown tokens render as empty."""
    resolver = _RESOLVERS.get(name)
    return resolver(live, ext) if resolver else ""


def render_filename(template: str, live: LiveSet, *, ext: str) -> str:
    """Apply ``template`` against ``live`` and return a relative path string
    (forward-slash separated).

    ``ext`` is the source file's extension *including* the leading dot
    (e.g. ``.opus``). Callers pass ``Path(src).suffix``. A literal dot right
    before ``{Ext}`` is dropped, so ``{Slug}.{Ext}`` and ``{Slug}{Ext}`` both
    render ``slug.opus``.
    """
    def replace(match: re.Match[str]) -> str:
        return _resolve_token(match.group("name"), live, ext)

    out = _TOKEN_RE.sub(replace, template.replace(".{Ext}", "{Ext}"))
    # Normalise path separators + collapse repeated slashes
    out = out.replace("\\", "/")
    out = re.sub(r"/{2,}", "/", out)
    return out.lstrip("/")

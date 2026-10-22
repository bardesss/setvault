from __future__ import annotations

import unicodedata
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import Artist, Party, Series, Venue
from setvault_core.services.catalog import EntityKind

_KIND_MODEL = {"artist": Artist, "venue": Venue, "party": Party, "series": Series}


def _is_latin(ch: str) -> bool:
    # "" (a mark with no base letter yet) is not Latin: keep the mark.
    return bool(ch) and "LATIN" in unicodedata.name(ch, "")


def normalized_name(name: str) -> str:
    """Fold case, strip accents/punctuation, collapse whitespace — a coarse key
    that catches the common auto-ingest near-duplicates ('DJ X' / 'dj  x.').

    Unicode-aware: letters, digits and combining marks of any script survive
    ('Кино', '坂本龍一', 'किनो'). Accents are stripped only from Latin letters
    ('Café' == 'Cafe'); in other scripts marks are meaningful ('ガ' != 'カ').
    Names with nothing word-like (e.g. emoji only) normalise to "" and are
    never clustered."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    out: list[str] = []
    base = ""
    for ch in decomposed:
        if unicodedata.category(ch).startswith("M"):
            if not _is_latin(base):
                out.append(ch)
            continue
        base = ch
        out.append(ch if ch.isalnum() else " ")
    return " ".join(unicodedata.normalize("NFC", "".join(out)).split())


async def find_duplicate_clusters(session: AsyncSession, kind: EntityKind) -> list[list]:
    model = _KIND_MODEL[kind]
    rows = (await session.execute(
        select(model).where(model.merged_into_id.is_(None))
    )).scalars().all()
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        key = normalized_name(row.name)
        if key:  # an empty key says nothing about identity
            groups[key].append(row)
    return [members for members in groups.values() if len(members) >= 2]

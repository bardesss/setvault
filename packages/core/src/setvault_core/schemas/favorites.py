from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from setvault_core.schemas.sets import SetSummaryOut


class FavoriteItemOut(SetSummaryOut):
    favorited_at: datetime


class FavoritesListOut(BaseModel):
    items: list[FavoriteItemOut]
    total: int

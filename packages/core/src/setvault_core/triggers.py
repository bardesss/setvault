"""What started an upgrade attempt or a rip: the values of
``SetUpgradeEvent.trigger`` and ``RipJob.trigger`` (both String(32))."""
from __future__ import annotations

SCHEDULED = "scheduled"  # the hourly upgrade search
SEARCH_NOW = "search_now"  # the Wanted page's manual search
BACKFILL = "backfill"  # the quality backfill's duplicate cleanup
DUPLICATES = "duplicates"  # the admin Duplicates page (discard, merged)
MONITOR = "monitor"
UPLOAD = "upload"
WATCH_FOLDER = "watch_folder"
URL_RIP = "url_rip"
SOURCE_SEARCH = "source_search"

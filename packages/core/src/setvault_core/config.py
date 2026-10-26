"""Process-wide configuration helpers shared by the web and worker apps."""
from __future__ import annotations

import os

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def redis_url() -> str:
    """The Redis URL from ``REDIS_URL``, read on every call (never cached) so
    a test that monkeypatches the environment is honoured."""
    return os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)

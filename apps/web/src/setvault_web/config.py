from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from setvault_core.config import DEFAULT_REDIS_URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = Field(default="dev-only-do-not-use-in-prod", min_length=16)
    database_url: str = "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault"
    redis_url: str = DEFAULT_REDIS_URL
    # No default on purpose: BASE_URL is required, and the session-cookie
    # ``Secure`` flag is derived from its scheme (see cookies.cookie_secure).
    # A silent ``http://`` default would fail *open* — a public deployment that
    # forgot to set BASE_URL would silently serve a non-Secure cookie. Empty
    # means "unconfigured", which cookie_secure() treats as fail-closed (Secure
    # on). An explicit ``http://`` value is a deliberate VPN/LAN choice.
    base_url: str = ""
    allow_1001tl_scrape: bool = Field(default=False, alias="SETVAULT_ALLOW_1001TL_SCRAPE")
    # tusd spools uploads under <cache>/tus (infra/docker/s6-rc.d/tusd/run).
    cache_path: str = Field(default="/srv/cache", alias="SETVAULT_CACHE_PATH")


@lru_cache
def get_settings() -> Settings:
    return Settings()

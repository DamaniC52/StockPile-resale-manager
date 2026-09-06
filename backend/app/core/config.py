"""Application settings, loaded from the environment.

Why a Settings class instead of scattered `os.environ["DATABASE_URL"]` calls:

1. **It fails at startup, not at 2am.** Pydantic validates every field when
   Settings is constructed. A missing DATABASE_URL crashes the app immediately
   with a clear message, instead of raising KeyError inside the first request
   that happens to touch the database.

2. **Types are real.** ACCESS_TOKEN_EXPIRE_MINUTES arrives from the environment
   as the *string* "60". Declaring it `int` makes pydantic coerce and validate
   it, so you never accidentally do arithmetic on a string.

3. **One documented place to look** for what this service needs to run.

This is the "config in the environment" rule from the Twelve-Factor App — the
same code artifact runs locally and on Render; only the environment differs.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Render/Vercel inject real environment variables and ship no .env file.
        # env_file is a local-dev convenience; actual env vars always win.
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str

    # --- Auth (Phase 2) ---
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- CORS ---
    # Comma-separated in the env file; split into a list by the property below.
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    `lru_cache` means the .env file is parsed exactly once per process rather
    than on every request. It also makes this function usable as a FastAPI
    dependency without re-reading the disk each time, and lets tests override
    settings by calling `get_settings.cache_clear()`.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment

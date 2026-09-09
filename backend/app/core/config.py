"""Application settings, validated from the environment at startup."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_driver(cls, value: str) -> str:
        """Force the psycopg 3 driver onto the URL.

        Managed providers hand out `postgres://...`, which SQLAlchemy rejects
        outright, and `postgresql://...`, which resolves to psycopg2 -- not
        installed here. Rewriting on the way in means the deployed service
        works with whatever the provider injects, unedited.
        """
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Same-origin in production via a Vercel rewrite, so this stays empty
    # there; it is the dev-server origin locally.
    CORS_ORIGINS: str = "http://localhost:5173"

    # Requests per window per client IP on the auth endpoints. The app is
    # internet-facing once deployed, and unlimited password guesses is the one
    # gap that matters without a WAF in front.
    AUTH_RATE_LIMIT: int = 10
    AUTH_RATE_WINDOW_SECONDS: int = 60

    # Which SearchService implementation get_search_service() returns. Postgres
    # is the default so a fresh clone works with no second datastore.
    SEARCH_BACKEND: Literal["postgres", "elasticsearch"] = "postgres"
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    # An alias, not a concrete index: reindexing builds a new index and swaps
    # the alias, so readers never see a half-built index.
    ELASTICSEARCH_INDEX: str = "stockpile-items"
    # How often the API process drains the search outbox, in seconds.
    SEARCH_SYNC_INTERVAL: float = 2.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

"""Application settings, validated from the environment at startup."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    CORS_ORIGINS: str = "http://localhost:5173"

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

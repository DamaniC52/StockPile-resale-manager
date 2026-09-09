"""Item search behind a swappable backend, selected by SEARCH_BACKEND."""

from functools import lru_cache

from app.core.config import get_settings
from app.search.base import SearchHit, SearchService
from app.search.elastic import ElasticIndexer, ElasticSearchService, make_client
from app.search.postgres import PostgresSearchService

__all__ = [
    "ElasticIndexer",
    "ElasticSearchService",
    "PostgresSearchService",
    "SearchHit",
    "SearchService",
    "get_indexer",
    "get_search_service",
]


@lru_cache
def _client():
    # One client per process: it owns a connection pool and is thread-safe.
    return make_client(get_settings().ELASTICSEARCH_URL)


def get_indexer() -> ElasticIndexer | None:
    """The write side of the index, or None when Postgres is the backend."""
    settings = get_settings()
    if settings.SEARCH_BACKEND != "elasticsearch":
        return None
    return ElasticIndexer(_client(), settings.ELASTICSEARCH_INDEX)


def get_search_service() -> SearchService:
    settings = get_settings()
    postgres = PostgresSearchService()
    if settings.SEARCH_BACKEND == "elasticsearch":
        # Postgres as the fallback: if the cluster is unreachable, search
        # degrades to the source of truth rather than to an error page.
        return ElasticSearchService(_client(), settings.ELASTICSEARCH_INDEX, fallback=postgres)
    return postgres

"""Elasticsearch backend: index definition, indexer, and search.

The index is addressed through an alias. Reindexing builds a fresh index and
swaps the alias in one atomic call, so readers never see a half-built index
and a bad mapping change can be rolled back by swapping the alias again.
"""

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from elasticsearch import Elasticsearch, TransportError
from elasticsearch import ApiError, ConnectionError as ESConnectionError
from elasticsearch.helpers import bulk
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.search.base import SearchHit, SearchService, is_bare_word, normalize_query

log = logging.getLogger(__name__)

# Mirrors the Postgres tsvector: name outranks source outranks size. Explicit
# mappings with dynamic=strict, so an unexpected field is an error at index
# time rather than a silently guessed type that cannot be changed later.
INDEX_SETTINGS = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        "filter": {
            "english_stemmer": {"type": "stemmer", "language": "english"},
            "english_stop": {"type": "stop", "stopwords": "_english_"},
            # Prefixes 2..15 chars, so "jorda" matches at index time without
            # a wildcard query. Kept off the main field: ngrams inflate the
            # index and would distort scoring on full-word matches.
            "edge_prefix": {"type": "edge_ngram", "min_gram": 2, "max_gram": 15},
        },
        "normalizer": {
            "lowercase": {"type": "custom", "filter": ["lowercase"]},
        },
        "analyzer": {
            # Same behaviour as Postgres's 'english' config: case-fold, fold
            # accents, drop stopwords, stem. "Hoodies" and "hoodie" meet at
            # "hoodi" on both backends, which is what lets one test suite
            # assert the same results against each.
            "item_text": {
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding", "english_stop", "english_stemmer"],
            },
            "item_prefix": {
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding", "edge_prefix"],
            },
            # The search side of the prefix field must NOT ngram the query, or
            # "jo" would match everything containing "j".
            "item_prefix_search": {
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding"],
            },
        },
    },
}

INDEX_MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        # keyword, never text: it is a filter, and filters are cached.
        "user_id": {"type": "keyword"},
        "name": {
            "type": "text",
            "analyzer": "item_text",
            "fields": {
                "prefix": {
                    "type": "text",
                    "analyzer": "item_prefix",
                    "search_analyzer": "item_prefix_search",
                }
            },
        },
        "source": {"type": "text", "analyzer": "item_text"},
        "size": {"type": "keyword", "normalizer": "lowercase"},
        "updated_at": {"type": "date"},
    },
}

SEARCH_FIELDS = ["name^3", "source^2", "size"]


def document_for(item: Item) -> dict:
    return {
        "user_id": str(item.user_id),
        "name": item.name,
        "source": item.source,
        "size": item.size,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def version_for(item: Item) -> int:
    """External version: updated_at as epoch milliseconds.

    With version_type=external_gte, Elasticsearch refuses to overwrite a
    document with an older version. Outbox rows can be applied out of order
    or twice and the index still converges on the newest state.
    """
    return int(item.updated_at.timestamp() * 1000) if item.updated_at else 0


@dataclass(frozen=True)
class IndexOp:
    op: Literal["index", "delete"]
    item_id: int
    version: int
    doc: dict | None = None


@dataclass(frozen=True)
class ApplyResult:
    ok: set[int]
    failed: dict[int, str]


def make_client(url: str) -> Elasticsearch:
    # Short timeouts: search is on the request path, and the fallback exists
    # precisely so a slow cluster degrades to Postgres rather than to a hang.
    return Elasticsearch(url, request_timeout=5, max_retries=1, retry_on_timeout=False)


class ElasticIndexer:
    """Owns the alias and the write side of the index."""

    def __init__(self, client: Elasticsearch, alias: str) -> None:
        self.client = client
        self.alias = alias

    def _new_index_name(self) -> str:
        return f"{self.alias}-{int(time.time() * 1000)}"

    def _create_index(self, name: str) -> None:
        self.client.indices.create(index=name, settings=INDEX_SETTINGS, mappings=INDEX_MAPPINGS)

    def ensure_index(self) -> None:
        """Create the index and alias on first run; no-op afterwards."""
        if self.client.indices.exists_alias(name=self.alias):
            return
        if self.client.indices.exists(index=self.alias):
            raise RuntimeError(
                f"{self.alias!r} exists as a concrete index, not an alias; "
                "delete it so the alias can be created"
            )
        name = self._new_index_name()
        self._create_index(name)
        self.client.indices.put_alias(index=name, name=self.alias)
        log.info("created search index %s behind alias %s", name, self.alias)

    def apply(self, ops: Iterable[IndexOp]) -> ApplyResult:
        """Apply index/delete operations in one bulk request."""
        actions = []
        for o in ops:
            action = {
                "_op_type": o.op,
                "_index": self.alias,
                "_id": o.item_id,
                "version": o.version,
                "version_type": "external_gte",
            }
            if o.op == "index":
                action["_source"] = o.doc
            actions.append(action)
        if not actions:
            return ApplyResult(ok=set(), failed={})

        ok: set[int] = {int(a["_id"]) for a in actions}
        failed: dict[int, str] = {}
        _, errors = bulk(self.client, actions, raise_on_error=False, stats_only=False)
        for err in errors:
            body = err.get("index") or err.get("delete") or {}
            item_id = int(body.get("_id", -1))
            status = body.get("status")
            # 409: the index already holds a newer version; that IS the desired
            # end state. 404 on delete: already gone. Both are success.
            if status == 409 or (status == 404 and "delete" in err):
                continue
            ok.discard(item_id)
            failed[item_id] = str(body.get("error", err))[:500]
        return ApplyResult(ok=ok, failed=failed)

    def reindex(self, db: Session, *, batch: int = 1000) -> str:
        """Rebuild from Postgres into a new index, then swap the alias.

        Readers keep using the old index until the new one is complete and
        refreshed, and the swap is a single atomic aliases call.
        """
        name = self._new_index_name()
        self._create_index(name)

        def actions():
            for item in db.execute(select(Item).execution_options(yield_per=batch)).scalars():
                yield {
                    "_op_type": "index",
                    "_index": name,
                    "_id": item.id,
                    "version": version_for(item),
                    "version_type": "external_gte",
                    "_source": document_for(item),
                }

        count, errors = bulk(self.client, actions(), chunk_size=batch, raise_on_error=False)
        if errors:
            self.client.indices.delete(index=name)
            raise RuntimeError(f"reindex failed on {len(errors)} documents; new index discarded")
        self.client.indices.refresh(index=name)

        old = []
        if self.client.indices.exists_alias(name=self.alias):
            old = list(self.client.indices.get_alias(name=self.alias).keys())
        swap = [{"remove": {"index": o, "alias": self.alias}} for o in old]
        swap.append({"add": {"index": name, "alias": self.alias}})
        self.client.indices.update_aliases(actions=swap)
        for o in old:
            self.client.indices.delete(index=o)
        log.info("reindexed %d items into %s", count, name)
        return name

    def refresh(self) -> None:
        """Make recent writes searchable now rather than within refresh_interval."""
        self.client.indices.refresh(index=self.alias)


class ElasticSearchService:
    """Search via Elasticsearch, degrading to another backend if it is unreachable."""

    def __init__(
        self,
        client: Elasticsearch,
        alias: str,
        fallback: SearchService | None = None,
    ) -> None:
        self.client = client
        self.alias = alias
        self.fallback = fallback

    def _query(self, user_id: int, query: str) -> dict:
        # simple_query_string is the closest analogue to websearch_to_tsquery:
        # it never raises on user input and supports "phrases", -exclusion and
        # OR. Its OR is '|', so the word form is translated for parity.
        exact = {
            "simple_query_string": {
                "query": query.replace(" OR ", " | "),
                "fields": SEARCH_FIELDS,
                "default_operator": "and",
                "flags": "AND|OR|NOT|PHRASE|WHITESPACE",
            }
        }
        should = [exact]
        if is_bare_word(query):
            should.append({"match": {"name.prefix": {"query": query, "boost": 2}}})
            # AUTO: 0 edits under 3 chars, 1 up to 5, 2 beyond. "jordn" -> "jordan".
            should.append({"match": {"name": {"query": query, "fuzziness": "AUTO"}}})
        return {
            "bool": {
                # filter, not must: tenancy is a yes/no test with no bearing on
                # score, and filter clauses are cached across requests.
                "filter": [{"term": {"user_id": str(user_id)}}],
                "should": should,
                "minimum_should_match": 1,
            }
        }

    def search(
        self, db: Session, *, user_id: int, query: str, limit: int = 50
    ) -> list[SearchHit]:
        query = normalize_query(query)
        if not query:
            return []
        try:
            res = self.client.search(
                index=self.alias,
                query=self._query(user_id, query),
                size=limit,
                source=False,
            )
        except (ESConnectionError, TransportError, ApiError) as exc:
            if self.fallback is None:
                raise
            log.warning("elasticsearch unavailable (%s); falling back", type(exc).__name__)
            return self.fallback.search(db, user_id=user_id, query=query, limit=limit)

        return [
            SearchHit(item_id=int(h["_id"]), score=float(h["_score"] or 0))
            for h in res["hits"]["hits"]
        ]

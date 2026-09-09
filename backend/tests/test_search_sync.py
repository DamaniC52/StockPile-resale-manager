"""Keeping Elasticsearch consistent with Postgres via the outbox.

Everything here needs a running cluster and skips without one.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.item import Item
from app.models.search_outbox import SearchOutbox
from app.models.user import User
from app.schemas.item import ItemCreate, ItemUpdate
from app.search.elastic import ElasticIndexer, ElasticSearchService, IndexOp, make_client
from app.search.outbox import drain, enqueue, pending_count
from app.search.postgres import PostgresSearchService
from app.services import inventory

pytestmark = pytest.mark.usefixtures("es_indexer")


@pytest.fixture
def user(db):
    u = User(email="sync@test", hashed_password="x")
    db.add(u)
    db.commit()
    return u


def payload(name: str, **overrides) -> ItemCreate:
    base = dict(name=name, quantity=1, unit_cost=Decimal("100.00"), purchased_at=date(2026, 1, 1))
    return ItemCreate(**{**base, **overrides})


def pending(db):
    return db.scalars(
        select(SearchOutbox).where(SearchOutbox.processed_at.is_(None))
    ).all()


def search(indexer, db, user_id, query):
    indexer.refresh()
    svc = ElasticSearchService(indexer.client, indexer.alias, fallback=None)
    return [h.item_id for h in svc.search(db, user_id=user_id, query=query)]


def test_create_writes_item_and_outbox_row_together(db, user):
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    rows = pending(db)
    assert [(r.item_id, r.op) for r in rows] == [(item.id, "index")]


def test_drain_makes_the_item_searchable(db, user, es_indexer):
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    assert search(es_indexer, db, user.id, "jordan") == []  # not yet drained

    assert drain(db, es_indexer) == 1
    assert pending_count(db) == 0
    assert search(es_indexer, db, user.id, "jordan") == [item.id]


def test_only_indexed_fields_trigger_a_reindex(db, user):
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    for r in pending(db):
        r.processed_at = r.created_at
    db.commit()

    inventory.update_lot(db, item=item, payload=ItemUpdate(unit_cost=Decimal("150.00")))
    assert pending(db) == [], "a cost change is invisible to search"

    inventory.update_lot(db, item=item, payload=ItemUpdate(name="Jordan 4 Black Cat"))
    assert [r.op for r in pending(db)] == ["index"]


def test_update_replaces_the_document(db, user, es_indexer):
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    drain(db, es_indexer)

    inventory.update_lot(db, item=item, payload=ItemUpdate(name="Yeezy Slide Bone"))
    drain(db, es_indexer)

    assert search(es_indexer, db, user.id, "jordan") == []
    assert search(es_indexer, db, user.id, "yeezy") == [item.id]


def test_delete_removes_the_document(db, user, es_indexer):
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    drain(db, es_indexer)
    assert search(es_indexer, db, user.id, "jordan") == [item.id]

    inventory.delete_lot(db, item=item)
    assert [r.op for r in pending(db)] == ["delete"]
    drain(db, es_indexer)
    assert search(es_indexer, db, user.id, "jordan") == []


def test_several_changes_to_one_item_collapse_to_its_final_state(db, user, es_indexer):
    item = inventory.create_lot(db, user_id=user.id, payload=payload("First Name"))
    inventory.update_lot(db, item=item, payload=ItemUpdate(name="Second Name"))
    inventory.update_lot(db, item=item, payload=ItemUpdate(name="Final Name"))
    assert len(pending(db)) == 3

    drain(db, es_indexer)
    assert pending_count(db) == 0
    assert search(es_indexer, db, user.id, "final") == [item.id]
    assert search(es_indexer, db, user.id, "first") == []


def test_stale_write_cannot_overwrite_a_newer_document(db, user, es_indexer):
    """External versioning: an older version arriving late is rejected, and
    that rejection counts as success because the index already holds the
    newer state."""
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Newest Name"))
    drain(db, es_indexer)

    stale = IndexOp(
        "index", item.id, version=1,
        doc={"user_id": str(user.id), "name": "Ancient Name", "source": None,
             "size": None, "updated_at": None},
    )
    result = es_indexer.apply([stale])
    assert result.ok == {item.id} and not result.failed

    assert search(es_indexer, db, user.id, "newest") == [item.id]
    assert search(es_indexer, db, user.id, "ancient") == []


def test_unreachable_cluster_leaves_rows_pending_for_retry(db, user):
    inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    dead = ElasticIndexer(make_client("http://127.0.0.1:1"), "unreachable")

    with pytest.raises(Exception):
        drain(db, dead)

    # Nothing was marked processed and nothing was lost.
    assert pending_count(db) == 1
    assert pending(db)[0].processed_at is None


def test_search_falls_back_to_postgres_when_cluster_is_unreachable(db, user):
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    svc = ElasticSearchService(
        make_client("http://127.0.0.1:1"), "unreachable", fallback=PostgresSearchService()
    )
    assert [h.item_id for h in svc.search(db, user_id=user.id, query="jordan")] == [item.id]


def test_reindex_swaps_the_alias_and_drops_the_old_index(db, user, es_indexer):
    client, alias = es_indexer.client, es_indexer.alias
    before = set(client.indices.get_alias(name=alias))

    a = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    b = inventory.create_lot(db, user_id=user.id, payload=payload("Yeezy Slide"))
    # Not drained on purpose: reindex reads Postgres, so it finds them anyway.
    new_name = es_indexer.reindex(db)

    after = set(client.indices.get_alias(name=alias))
    assert after == {new_name}
    assert not (before & after), "old index removed"
    assert search(es_indexer, db, user.id, "jordan") == [a.id]
    assert search(es_indexer, db, user.id, "yeezy") == [b.id]


def test_drain_of_an_already_deleted_item_is_a_delete(db, user, es_indexer):
    """An 'index' row for an item that no longer exists must not fail forever."""
    item = inventory.create_lot(db, user_id=user.id, payload=payload("Jordan 4 Bred"))
    db.delete(item)  # bypassing delete_lot, so only the 'index' row exists
    db.commit()

    assert drain(db, es_indexer) == 1
    assert pending_count(db) == 0

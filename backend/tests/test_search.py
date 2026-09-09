"""Search behaviour, asserted identically against every backend.

Parametrized over Postgres and Elasticsearch: the same query must return the
same items from either, which is what makes SearchService a real interface
rather than two features that happen to share a name. The Elasticsearch cases
skip when the cluster is not running.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.item import Item
from app.models.user import User
from app.search.elastic import ElasticSearchService
from app.search.postgres import PostgresSearchService

LOTS = [
    ("Jordan 4 Retro Bred", "10.5", "SNKRS"),
    ("Travis Scott Jordan 1 Low", "11", "GOAT"),
    ("Supreme Box Logo Hoodie", "M", "Supreme"),
    # Bought FROM Supreme but not named Supreme: ranks below the hoodie.
    ("Palace Tri-Ferg Tee", "L", "Supreme"),
    ("Nike Dunk Low Panda", "8.5", "Retail"),
    ("New Balance 990v6 Grey", "9", "Retail"),
]


def _lot(user_id: int, name: str, size: str, source: str | None) -> Item:
    return Item(
        user_id=user_id, name=name, size=size, source=source,
        quantity=1, quantity_remaining=1,
        unit_cost=Decimal("100.00"), purchased_at=date(2026, 1, 1),
    )


@pytest.fixture
def seeded(db):
    """One user with six lots, and a second user with a colliding name."""
    owner = User(email="owner@test", hashed_password="x")
    other = User(email="other@test", hashed_password="x")
    db.add_all([owner, other])
    db.flush()
    db.add_all(_lot(owner.id, *row) for row in LOTS)
    # Every search below must ignore this one.
    db.add(_lot(other.id, "Jordan 4 Retro Bred", "10.5", None))
    db.commit()
    return owner, other


@pytest.fixture(params=["postgres", "elasticsearch"])
def svc(request, db, seeded):
    if request.param == "postgres":
        return PostgresSearchService()
    # Resolved lazily so only the Elasticsearch cases skip when it is down.
    indexer = request.getfixturevalue("es_indexer")
    indexer.reindex(db)
    # No fallback here: a broken Elasticsearch must fail the test, not quietly
    # pass by answering from Postgres.
    return ElasticSearchService(indexer.client, indexer.alias, fallback=None)


def names(db, hits):
    by_id = {i.id: i.name for i in db.query(Item).all()}
    return [by_id[h.item_id] for h in hits]


def test_exact_word(db, seeded, svc):
    found = names(db, svc.search(db, user_id=seeded[0].id, query="jordan"))
    assert sorted(found) == ["Jordan 4 Retro Bred", "Travis Scott Jordan 1 Low"]


def test_stemming_matches_plural(db, seeded, svc):
    """'hoodies' finds 'Hoodie' — a substring match never would."""
    assert names(db, svc.search(db, user_id=seeded[0].id, query="hoodies")) == [
        "Supreme Box Logo Hoodie"
    ]


def test_prefix_matches_a_half_typed_word(db, seeded, svc):
    found = names(db, svc.search(db, user_id=seeded[0].id, query="jorda"))
    assert len(found) == 2


def test_typo_still_matches(db, seeded, svc):
    found = names(db, svc.search(db, user_id=seeded[0].id, query="jordn"))
    assert len(found) == 2


def test_words_may_be_out_of_order(db, seeded, svc):
    found = names(db, svc.search(db, user_id=seeded[0].id, query="grey balance"))
    assert found == ["New Balance 990v6 Grey"]


def test_quoted_phrase(db, seeded, svc):
    found = names(db, svc.search(db, user_id=seeded[0].id, query='"box logo"'))
    assert found == ["Supreme Box Logo Hoodie"]


def test_or_operator(db, seeded, svc):
    found = names(db, svc.search(db, user_id=seeded[0].id, query="panda OR grey"))
    assert sorted(found) == ["New Balance 990v6 Grey", "Nike Dunk Low Panda"]


def test_exclusion_is_not_defeated_by_the_fuzzy_branch(db, seeded, svc):
    """Regression. Fuzzy matching used to OR excluded rows back in.

    'nike -dunk' excludes Dunk on the exact branch, but the raw string is still
    fuzzily similar to 'Nike Dunk Low Panda'. The fuzzy branch now runs only for
    a single bare word, on both backends, because the rule lives in base.py.
    """
    assert svc.search(db, user_id=seeded[0].id, query="nike -dunk") == []


def test_name_match_outranks_source_match(db, seeded, svc):
    """Two lots match 'supreme'; the one NAMED Supreme comes first."""
    found = names(db, svc.search(db, user_id=seeded[0].id, query="supreme"))
    assert found == ["Supreme Box Logo Hoodie", "Palace Tri-Ferg Tee"]


def test_scoped_to_the_caller(db, seeded, svc):
    owner, other = seeded
    assert len(svc.search(db, user_id=owner.id, query="jordan")) == 2
    assert len(svc.search(db, user_id=other.id, query="jordan")) == 1


def test_no_match_is_empty(db, seeded, svc):
    assert svc.search(db, user_id=seeded[0].id, query="zzzznothing") == []


@pytest.mark.parametrize("query", ["", "   ", "\t"])
def test_blank_query_short_circuits(db, seeded, svc, query):
    assert svc.search(db, user_id=seeded[0].id, query=query) == []


@pytest.mark.parametrize("query", ["'", '"', "\\", "&|!():*", "a' OR '1'='1"])
def test_punctuation_never_raises(db, seeded, svc, query):
    svc.search(db, user_id=seeded[0].id, query=query)


# ---- Postgres-specific: the generated column is a database feature ---------


def test_generated_column_is_maintained_by_postgres(db, seeded):
    item = db.query(Item).filter(Item.name == "Nike Dunk Low Panda").one()
    assert "panda" in item.search_vector

    item.name = "Asics Gel Lyte III"
    db.commit()
    db.refresh(item)
    assert "asic" in item.search_vector
    assert "panda" not in item.search_vector

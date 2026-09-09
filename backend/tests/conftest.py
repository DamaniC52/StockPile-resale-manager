"""Test fixtures.

Tests run against a real Postgres database, not SQLite and not mocks. The
behaviours most worth testing here — the oversell guard, the CHECK constraints,
the composite foreign keys — are database behaviours. SQLite has no partial
indexes and different locking; a mocked session would let overselling through
and the test would pass while the bug shipped.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.models.item import Item
from app.models.marketplace import Marketplace
from app.models.user import User

# A separate database so a test run can never truncate development data.
TEST_DB = "stockpile_test"

# Tables in dependency order for truncation.
_TABLES = "search_outbox, sales, listings, price_snapshots, items, products, users, marketplaces"


@pytest.fixture(scope="session")
def engine():
    settings = get_settings()
    admin_url = settings.DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    test_url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"

    # CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()

    eng = create_engine(test_url, pool_pre_ping=True)

    # Extensions the models' indexes depend on. create_all does not create
    # these, and gin_trgm_ops fails without pg_trgm.
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    # drop_all before create_all. create_all only creates MISSING TABLES -- it
    # will not add a column to a table that already exists, so a schema change
    # would otherwise leave the test database silently stale and every test
    # failing on a column that "does not exist".
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Session:
    """A clean database and a session, per test.

    Truncating rather than wrapping each test in a rollback: the concurrency
    test needs two connections to really commit, which an outer transaction
    would prevent.
    """
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def session_factory(engine):
    """For tests that need more than one independent session."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def user(db: Session) -> User:
    u = User(email="seller@test.com", hashed_password="x")
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def marketplace(db: Session) -> Marketplace:
    m = Marketplace(name="StockX", slug="stockx")
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def lot(db: Session, user: User) -> Item:
    """A lot of 3 units at $60 each, with a $20 flat acquisition fee.

    Chosen so the fee does not divide evenly: 20 / 3 = 6.6667, which is exactly
    the case the allocation logic exists to handle.
    """
    item = Item(
        user_id=user.id,
        name="Jordan 4 Bred",
        quantity=3,
        quantity_remaining=3,
        unit_cost=Decimal("60.00"),
        acquisition_fee_total=Decimal("20.00"),
        purchased_at=date(2026, 8, 1),
    )
    db.add(item)
    db.commit()
    return item


# ---------------------------------------------------------------------------
# Elasticsearch. Tests that need it skip, rather than fail, when it is down, so
# the Postgres suite still runs on a machine without the container.
# ---------------------------------------------------------------------------
ES_TEST_ALIAS = "stockpile-items-test"


@pytest.fixture(scope="session")
def es_client():
    from app.search.elastic import make_client

    client = make_client(get_settings().ELASTICSEARCH_URL)
    try:
        reachable = client.ping()
    except Exception:
        reachable = False
    if not reachable:
        pytest.skip("elasticsearch is not reachable")
    yield client
    client.close()


def _drop_alias(client, alias: str) -> None:
    if client.indices.exists_alias(name=alias):
        for name in client.indices.get_alias(name=alias):
            client.indices.delete(index=name)


@pytest.fixture
def es_indexer(es_client):
    """A fresh, empty index behind the test alias, torn down afterwards."""
    from app.search.elastic import ElasticIndexer

    _drop_alias(es_client, ES_TEST_ALIAS)
    indexer = ElasticIndexer(es_client, ES_TEST_ALIAS)
    indexer.ensure_index()
    yield indexer
    _drop_alias(es_client, ES_TEST_ALIAS)

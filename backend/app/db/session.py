"""Database engine and session factory.

Two concepts that are easy to conflate:

* **Engine** — one per application. It owns the *connection pool*: a set of
  reusable TCP connections to Postgres. Opening a connection costs milliseconds
  and Postgres forks a backend process per connection, so you pool them rather
  than connecting per request. Creating an Engine is expensive; creating it once
  at import time is correct.

* **Session** — one per request (per "unit of work"). It borrows a connection
  from the pool when it first needs one, tracks the objects you've loaded and
  modified, and flushes them as a single transaction on commit.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    # Checks a pooled connection is still alive with a cheap ping before handing
    # it out. Without this, connections idle-killed by the database (or by a
    # laptop sleeping, or Render recycling) surface as a confusing
    # "server closed the connection unexpectedly" on a random request.
    pool_pre_ping=True,
    # Set to True temporarily to log every SQL statement SQLAlchemy emits.
    # Genuinely the fastest way to learn what the ORM is actually doing —
    # and to catch N+1 query problems, where you see the same SELECT 50 times.
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    # THE important flag. By default, commit() marks every loaded object as
    # "expired", so the next attribute access re-SELECTs it. In FastAPI that
    # re-read happens *after* the route returns, while the response is being
    # serialized — by which point the session may be closed, giving you a
    # DetachedInstanceError, or a burst of surprise queries if it isn't.
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped Session.

    The `yield` makes this a generator dependency: FastAPI runs the code before
    the yield, injects the value, then runs the cleanup afterwards — even if the
    route raised. The `with` block guarantees the connection returns to the pool.

    Note this deliberately does NOT commit. Committing here would mean every
    read-only request opens a write transaction, and it would hide *where* the
    transaction boundary is. Services own their own commits; that keeps the
    "which writes are atomic together" question answerable by reading one file.
    """
    with SessionLocal() as session:
        yield session

"""Engine and session factory."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    # Validates pooled connections before use, so idle-killed connections don't
    # surface as random request failures.
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    # Without this, commit() expires loaded objects and FastAPI's response
    # serialization triggers refreshes on a closing session.
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """Request-scoped session. Services own their own commits."""
    with SessionLocal() as session:
        yield session

"""Transactional outbox for search index updates.

Postgres is the source of truth; the search index is derived from it. Writing
to both in one request is the obvious approach and the wrong one: if the
database commit succeeds and the index write fails — or the process dies
between them — the two diverge with nothing to reconcile them.

Instead, the item change and a row here are written in the SAME transaction.
Either both exist or neither does. A separate drainer reads pending rows and
applies them to the index, retrying on failure. The index is therefore
eventually consistent with the database, with at-least-once delivery, and a
failed index write can never lose an update.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SearchOutbox(Base):
    __tablename__ = "search_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # No foreign key: a 'delete' row must outlive the item it refers to.
    item_id: Mapped[int]
    user_id: Mapped[int]
    op: Mapped[str] = mapped_column(String(8))

    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    processed_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("op IN ('index','delete')", name="op_valid"),
        # The drainer's query. Partial, so it holds only the backlog and stays
        # small no matter how many rows have been processed.
        Index(
            "ix_search_outbox_pending",
            "created_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )

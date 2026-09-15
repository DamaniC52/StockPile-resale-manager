"""Transactional outbox for search index updates.
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

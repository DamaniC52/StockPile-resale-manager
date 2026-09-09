"""Item — a lot of N identical units acquired together.

One row is not one unit: "5 pairs, size 10, bought the same day at the same
price". Sales draw partial quantities from the lot.
"""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    case,
    literal,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Money, TimestampMixin
from app.models.enums import ItemCondition, StockStatus, sql_values

if TYPE_CHECKING:
    from app.models.listing import Listing
    from app.models.product import Product
    from app.models.sale import Sale
    from app.models.user import User


class Item(TimestampMixin, Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # NULL for one-off items with no style code. RESTRICT so deleting a catalog
    # entry can't cascade away someone's inventory.
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )

    name: Mapped[str] = mapped_column(String(200))
    size: Mapped[str | None] = mapped_column(String(20))
    condition: Mapped[str] = mapped_column(
        String(20), server_default=text(f"'{ItemCondition.NEW.value}'")
    )

    quantity: Mapped[int]
    # Denormalized so `quantity_remaining >= 0` is row-local and therefore
    # enforceable by CHECK. The computed equivalent spans two tables, and a
    # CHECK constraint cannot reference another table.
    quantity_remaining: Mapped[int]

    # Per-unit cost as entered; a lot total would force lossy division.
    unit_cost: Mapped[Money]
    # Flat costs that don't scale with quantity (inbound shipping, buyer premium).
    acquisition_fee_total: Mapped[Money] = mapped_column(server_default=text("0"))

    purchased_at: Mapped[date]
    source: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)

    # A STORED generated column: Postgres recomputes it on every insert and
    # update, so it can never drift from the columns it derives from.
    #
    # Unlike quantity_remaining, this qualifies. A generated expression must be
    # IMMUTABLE and reference only this row -- the two-argument to_tsvector is
    # immutable (the one-argument form is not; it reads a session setting), and
    # every input is a column of this row.
    #
    # setweight ranks a name match above a source match, which ts_rank uses to
    # order results.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(name, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(source, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(size, '')), 'C')",
            persisted=True,
        ),
        nullable=True,
    )

    user: Mapped["User"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship(back_populates="items")
    sales: Mapped[list["Sale"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    listings: Mapped[list["Listing"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    @hybrid_property
    def stock_status(self) -> str:
        """Derived, not stored: a lot can be part-sold, which no single enum captures."""
        if self.quantity_remaining == 0:
            return StockStatus.SOLD_OUT
        if self.quantity_remaining < self.quantity:
            return StockStatus.PARTIALLY_SOLD
        return StockStatus.IN_STOCK

    @stock_status.inplace.expression
    @classmethod
    def _stock_status_expr(cls):
        """SQL form, so the status is filterable in a query."""
        return case(
            (cls.quantity_remaining == 0, literal(StockStatus.SOLD_OUT.value)),
            (
                cls.quantity_remaining < cls.quantity,
                literal(StockStatus.PARTIALLY_SOLD.value),
            ),
            else_=literal(StockStatus.IN_STOCK.value),
        )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("quantity_remaining >= 0", name="remaining_nonneg"),
        CheckConstraint("quantity_remaining <= quantity", name="remaining_le_quantity"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_nonneg"),
        CheckConstraint("acquisition_fee_total >= 0", name="acq_fee_nonneg"),
        CheckConstraint(
            f"condition IN ({sql_values(ItemCondition)})", name="condition_valid"
        ),
        # Referent for the composite tenancy FKs on listings and sales.
        UniqueConstraint("id", "user_id"),
        Index("ix_items_user_id_purchased_at", "user_id", "purchased_at"),
        Index(
            "ix_items_user_in_stock",
            "user_id",
            postgresql_where=text("quantity_remaining > 0"),
        ),
        # GIN, not B-tree: a tsvector holds many lexemes per row, and GIN is the
        # inverted index that maps each lexeme back to the rows containing it.
        Index("ix_items_search_vector", "search_vector", postgresql_using="gin"),
        # Trigram index for partial words. Full-text search matches whole
        # lexemes, so "jorda" finds nothing; trigrams cover typos and prefixes.
        Index(
            "ix_items_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Item id={self.id} {self.name!r} "
            f"{self.quantity_remaining}/{self.quantity} left>"
        )

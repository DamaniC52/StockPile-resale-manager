"""Item — a LOT of N identical units bought together.

This is the central design decision of the whole app, so it's worth stating
plainly: one row here is not one sneaker. It is "5 identical pairs, size 10,
bought on the same day for the same price."

The alternative (one row per physical unit, called *serialized inventory*) is
more expressive but 5x the rows and makes every write path harder. We traded
per-unit identity for simplicity. The escape hatch is clean: anything needing
unit-level tracking is just a lot with quantity = 1.
"""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    case,
    literal,
    text,
)
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

    # ---------------------------------------------------------------- ownership
    # ondelete="CASCADE": deleting a user deletes their items. Enforced by
    # POSTGRES, so it holds even for a DELETE typed directly into psql.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Optional link to the shared product catalog. NULL for one-off items with
    # no SKU (a vintage jacket). ondelete="RESTRICT" means Postgres REFUSES to
    # delete a product that items still point at, rather than silently
    # cascading away someone's inventory.
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )

    # ------------------------------------------------------------- description
    # Denormalized display label. Duplicates product.name when product_id is
    # set — deliberately, so items with no catalog entry still have a name.
    name: Mapped[str] = mapped_column(String(200))
    size: Mapped[str | None] = mapped_column(String(20))  # "10.5", "M", "OS"
    condition: Mapped[str] = mapped_column(
        String(20), server_default=text(f"'{ItemCondition.NEW.value}'")
    )

    # ------------------------------------------------------- quantity and cost
    # Units originally acquired. Edited only to correct a miscount.
    quantity: Mapped[int]

    # Units still unsold. DENORMALIZED — see the class docstring note below and
    # the CHECK constraints, which are the entire reason this column exists.
    quantity_remaining: Mapped[int]

    # What the user paid PER UNIT. Stored as typed, never as total/quantity:
    # $100 for 3 units is $33.3333... which is unstorable without losing a cent.
    unit_cost: Mapped[Money]

    # Costs attached to the whole purchase rather than to each unit: inbound
    # shipping, a buyer's premium at auction. Kept SEPARATE from unit_cost
    # because it doesn't scale with quantity — correcting quantity from 3 to 4
    # should not change a flat $20 shipping charge.
    acquisition_fee_total: Mapped[Money] = mapped_column(server_default=text("0"))

    # ---------------------------------------------------------------- metadata
    purchased_at: Mapped[date]  # a plain DATE — nobody cares about the second
    source: Mapped[str | None] = mapped_column(String(100))  # "SNKRS", "Goodwill"
    notes: Mapped[str | None] = mapped_column(Text)  # unbounded; no length limit

    # ----------------------------------------------------------- relationships
    user: Mapped["User"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship(back_populates="items")
    sales: Mapped[list["Sale"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    listings: Mapped[list["Listing"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    # ------------------------------------------------------------ derived state
    @hybrid_property
    def stock_status(self) -> str:
        """Sold-through state, DERIVED rather than stored.

        There is deliberately no `status` column. With lots, a single enum is
        literally unrepresentable: "3 sold, 2 in stock" has no one value. And a
        stored copy of this would be denormalization with no invariant the
        database could enforce — all of the drift risk, none of the guarantee.
        """
        if self.quantity_remaining == 0:
            return StockStatus.SOLD_OUT
        if self.quantity_remaining < self.quantity:
            return StockStatus.PARTIALLY_SOLD
        return StockStatus.IN_STOCK

    @stock_status.inplace.expression
    @classmethod
    def _stock_status_expr(cls):
        """The SQL twin of the property above.

        A `hybrid_property` has two bodies. On an instance you get the Python
        version. Used inside a query you get THIS one, compiled to a SQL CASE
        expression — so `WHERE stock_status = 'sold_out'` runs in the database
        instead of loading every row into Python to filter it.
        """
        return case(
            (cls.quantity_remaining == 0, literal(StockStatus.SOLD_OUT.value)),
            (cls.quantity_remaining < cls.quantity, literal(StockStatus.PARTIALLY_SOLD.value)),
            else_=literal(StockStatus.IN_STOCK.value),
        )

    # -------------------------------------------------------- table-level rules
    __table_args__ = (
        # A lot of zero units is meaningless data.
        CheckConstraint("quantity > 0", name="quantity_positive"),
        # THE oversell guard. `quantity_remaining` is a single column on a single
        # row, which makes this predicate checkable by Postgres. The computed
        # alternative (quantity - SUM(sales.quantity_sold)) spans two tables, and
        # a CHECK constraint CANNOT reference another table — so it could never be
        # enforced at all. That is the real reason this column is denormalized:
        # not speed, but the ability to have a database-level guarantee.
        CheckConstraint("quantity_remaining >= 0", name="remaining_nonneg"),
        # Catches a bad void/refund putting back more than was ever bought.
        CheckConstraint("quantity_remaining <= quantity", name="remaining_le_quantity"),
        CheckConstraint("unit_cost >= 0", name="unit_cost_nonneg"),
        CheckConstraint("acquisition_fee_total >= 0", name="acq_fee_nonneg"),
        CheckConstraint(
            f"condition IN ({sql_values(ItemCondition)})", name="condition_valid"
        ),
        # Redundant for uniqueness (id alone is already unique) — it exists purely
        # so `sales` and `listings` can declare a COMPOSITE foreign key against
        # (id, user_id). Postgres requires a unique constraint on the referenced
        # column pair. See sale.py for what that buys us.
        # No name= given, so the NAMING_CONVENTION generates it:
        # uq_items_id_user_id. Passing name= explicitly would override the
        # convention and give you an inconsistently-named constraint.
        # (CHECK constraints are the exception — the convention's
        # `%(constraint_name)s` placeholder requires you to pass one.)
        UniqueConstraint("id", "user_id"),
        # The inventory list page: WHERE user_id = ? ORDER BY purchased_at DESC.
        # One index serves both the filter and the sort.
        #
        # No DESC needed: Postgres can scan a B-tree index backwards, so an
        # ascending index satisfies a descending ORDER BY at the same cost.
        # DESC in an index only matters for MIXED-direction sorts.
        Index("ix_items_user_id_purchased_at", "user_id", "purchased_at"),
        # A PARTIAL index — it only contains rows matching the WHERE clause.
        # "Show my current inventory" is the most common query in the app, and
        # this index stays small forever because sold-out lots drop out of it.
        Index(
            "ix_items_user_in_stock",
            "user_id",
            postgresql_where=text("quantity_remaining > 0"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Item id={self.id} {self.name!r} "
            f"{self.quantity_remaining}/{self.quantity} left>"
        )

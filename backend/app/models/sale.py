"""Sale — units of a lot leaving inventory. Where profit is computed.

Two ideas carry this table.

**1. Partial sales.** A sale consumes `quantity_sold` units from a lot, not the
whole lot. Selling 2 of 5 leaves 3. The counter on the item is decremented in
the same transaction (see services/sales.py, Phase 4).

**2. The cost basis is SNAPSHOTTED, not joined.** `unit_cost_snapshot` and
`acq_fee_allocated` are copied from the item at the moment of sale and never
recomputed. Two reasons:

  * *Accounting.* A recorded sale is a historical fact. If the user fixes a
    cost-price typo in June, March's reported profit must not silently change.
    This is exactly why an invoice line copies the price instead of joining to
    a products table. The general name for the idea is a point-in-time snapshot.

  * *Architecture.* It makes `sales` self-sufficient for profit. Every dashboard
    number becomes a single-table SUM with no joins at all — which is both much
    faster and what lets net_profit exist as a SQL expression below.

The cost is duplicated data, and you should say so out loud rather than hide it:
"I chose write-time snapshotting over read-time derivation because financial
records need point-in-time immutability, and I documented that editing an item's
cost is not retroactive."
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Money, TimestampMixin

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.listing import Listing
    from app.models.marketplace import Marketplace


class Sale(TimestampMixin, Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ------------------------------------------------------------------ links
    # Plain columns; the FKs are composite and declared in __table_args__.
    user_id: Mapped[int]
    item_id: Mapped[int]  # NOT NULL — profit is impossible without the lot

    # NULLABLE on purpose. Plenty of sales happen with no FlipTrack listing:
    # cash in person, a friend, a DM, or the user simply forgot to log the
    # listing first. Requiring it would force fake listing rows, which would
    # corrupt the sell-through statistics that `listings` exists to produce.
    listing_id: Mapped[int | None]

    # DENORMALIZED from the listing, and NOT NULL. "Net profit by marketplace"
    # is a headline dashboard chart; it must not depend on a nullable join.
    # Off-platform sales point at a synthetic 'direct' marketplace row.
    marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("marketplaces.id"), index=True
    )

    # --------------------------------------------------------------- the money
    quantity_sold: Mapped[int]
    unit_price: Mapped[Money]  # per unit, BEFORE any fees

    platform_fee: Mapped[Money] = mapped_column(server_default=text("0"))
    shipping_cost: Mapped[Money] = mapped_column(server_default=text("0"))  # seller-paid
    other_fees: Mapped[Money] = mapped_column(server_default=text("0"))

    # ---- cost basis snapshot: written once at sale time, never recomputed ----
    unit_cost_snapshot: Mapped[Money]
    # This sale's share of the lot's flat acquisition fee. Allocated by
    # services/sales.py so that, across the whole life of the lot, the shares
    # sum to EXACTLY the original fee — no pennies lost to rounding.
    acq_fee_allocated: Mapped[Money] = mapped_column(server_default=text("0"))

    # ------------------------------------------------------------------ timing
    sold_at: Mapped[datetime]
    # Marketplaces hold funds. Distinguishing "sold" from "paid out" is what
    # makes a cash-flow view possible later.
    payout_at: Mapped[datetime | None]

    external_order_id: Mapped[str | None] = mapped_column(String(64))

    item: Mapped["Item"] = relationship(back_populates="sales")
    listing: Mapped["Listing | None"] = relationship(back_populates="sales")
    marketplace: Mapped["Marketplace"] = relationship()

    # ------------------------------------------------------------ profit math
    # Each of these has a Python body AND a SQL body. The Python one runs on an
    # instance (`sale.net_profit`); the SQL one runs inside a query
    # (`func.sum(Sale.net_profit)`), which is what makes the dashboard possible.
    #
    # Every input is a column on THIS row — no joins, no subqueries — which is
    # the payoff from snapshotting the cost basis.

    @hybrid_property
    def revenue(self):
        """Gross sale amount, before fees."""
        return self.unit_price * self.quantity_sold

    @revenue.inplace.expression
    @classmethod
    def _revenue_expr(cls):
        return (cls.unit_price * cls.quantity_sold).label("revenue")

    @hybrid_property
    def cogs(self):
        """Cost of Goods Sold: what these units cost us to acquire."""
        return self.unit_cost_snapshot * self.quantity_sold + self.acq_fee_allocated

    @cogs.inplace.expression
    @classmethod
    def _cogs_expr(cls):
        return (
            cls.unit_cost_snapshot * cls.quantity_sold + cls.acq_fee_allocated
        ).label("cogs")

    @hybrid_property
    def net_profit(self):
        """What actually landed in our pocket.

        Note this composes `revenue` and `cogs` rather than repeating their
        formulas. In the Python body those resolve to Decimals; in the SQL body
        they resolve to SQL fragments. One definition, two evaluation contexts —
        that is the whole point of a hybrid.
        """
        return (
            self.revenue
            - self.platform_fee
            - self.shipping_cost
            - self.other_fees
            - self.cogs
        )

    @net_profit.inplace.expression
    @classmethod
    def _net_profit_expr(cls):
        return (
            cls.revenue
            - cls.platform_fee
            - cls.shipping_cost
            - cls.other_fees
            - cls.cogs
        ).label("net_profit")

    __table_args__ = (
        # Tenancy enforced by the database — a sale cannot claim an item that
        # belongs to a different user. Same mechanism as listings.
        ForeignKeyConstraint(
            ["item_id", "user_id"],
            ["items.id", "items.user_id"],
            ondelete="CASCADE",
        ),
        # Stops a sale referencing listing #99 (which belongs to item #3) while
        # claiming item #7. Without this, nothing prevents that mismatch.
        #
        # Subtle and worth knowing: this is a MATCH SIMPLE foreign key, meaning
        # when ANY of its columns is NULL the whole constraint is skipped. Since
        # listing_id is nullable, off-platform sales pass freely — exactly the
        # behaviour we want, and it falls out of the SQL standard for free.
        ForeignKeyConstraint(
            ["listing_id", "item_id"],
            ["listings.id", "listings.item_id"],
            ondelete="SET NULL",
        ),
        CheckConstraint("quantity_sold > 0", name="quantity_sold_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonneg"),
        CheckConstraint("platform_fee >= 0", name="platform_fee_nonneg"),
        CheckConstraint("shipping_cost >= 0", name="shipping_cost_nonneg"),
        # Deliberately NOT constrained: net_profit >= 0. Losing money on a flip
        # is a real and important outcome, not a data error.
        #
        # Makes importing marketplace order histories IDEMPOTENT: re-running an
        # import cannot create duplicate sales, because the second insert
        # violates this. Cheap protection against a genuinely nasty bug class.
        UniqueConstraint("marketplace_id", "external_order_id"),
        # THE dashboard index. Every profit-over-time aggregation is
        # `WHERE user_id = ? AND sold_at >= ?`, and this serves filter + sort.
        Index("ix_sales_user_id_sold_at", "user_id", "sold_at"),
        # Lot detail page, the fee-allocation SUM in record_sale, and the
        # composite FK's cascade.
        Index("ix_sales_item_id_user_id", "item_id", "user_id"),
        Index("ix_sales_listing_id", "listing_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Sale id={self.id} item={self.item_id} "
            f"x{self.quantity_sold} @{self.unit_price}>"
        )

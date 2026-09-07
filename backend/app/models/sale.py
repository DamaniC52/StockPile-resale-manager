"""Sale — units leaving a lot, and the profit they produced.

Cost basis is snapshotted at sale time rather than joined from the item, so
correcting an item's cost later cannot rewrite historical profit. It also keeps
every PNL aggregation a single-table SUM.
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

    # No per-column ForeignKey: covered by the composite FKs below.
    user_id: Mapped[int]
    item_id: Mapped[int]
    # Nullable: cash and off-platform sales have no listing record.
    listing_id: Mapped[int | None]

    # Denormalized from the listing so profit-by-marketplace needs no join.
    marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("marketplaces.id"), index=True
    )

    quantity_sold: Mapped[int]
    unit_price: Mapped[Money]
    platform_fee: Mapped[Money] = mapped_column(server_default=text("0"))
    shipping_cost: Mapped[Money] = mapped_column(server_default=text("0"))
    other_fees: Mapped[Money] = mapped_column(server_default=text("0"))

    # Cost basis, copied at sale time and never recomputed.
    unit_cost_snapshot: Mapped[Money]
    # This sale's share of the lot's flat acquisition fee; allocated so the
    # shares sum to exactly the original total across the lot's lifetime.
    acq_fee_allocated: Mapped[Money] = mapped_column(server_default=text("0"))

    sold_at: Mapped[datetime]
    payout_at: Mapped[datetime | None]
    external_order_id: Mapped[str | None] = mapped_column(String(64))

    item: Mapped["Item"] = relationship(back_populates="sales", overlaps="sales")
    listing: Mapped["Listing | None"] = relationship(
        back_populates="sales", overlaps="item,sales"
    )
    marketplace: Mapped["Marketplace"] = relationship()

    # Each of these has a SQL twin so the dashboard can aggregate in the
    # database instead of loading every row into Python.

    @hybrid_property
    def revenue(self):
        return self.unit_price * self.quantity_sold

    @revenue.inplace.expression
    @classmethod
    def _revenue_expr(cls):
        return (cls.unit_price * cls.quantity_sold).label("revenue")

    @hybrid_property
    def cogs(self):
        return self.unit_cost_snapshot * self.quantity_sold + self.acq_fee_allocated

    @cogs.inplace.expression
    @classmethod
    def _cogs_expr(cls):
        return (
            cls.unit_cost_snapshot * cls.quantity_sold + cls.acq_fee_allocated
        ).label("cogs")

    @hybrid_property
    def net_profit(self):
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
        # Tenancy as a constraint; see listings.
        ForeignKeyConstraint(
            ["item_id", "user_id"],
            ["items.id", "items.user_id"],
            ondelete="CASCADE",
        ),
        # A sale's listing must belong to the same item. MATCH SIMPLE semantics
        # skip the check when listing_id is NULL, which is what off-platform
        # sales need.
        ForeignKeyConstraint(
            ["listing_id", "item_id"],
            ["listings.id", "listings.item_id"],
            ondelete="SET NULL",
        ),
        CheckConstraint("quantity_sold > 0", name="quantity_sold_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonneg"),
        CheckConstraint("platform_fee >= 0", name="platform_fee_nonneg"),
        CheckConstraint("shipping_cost >= 0", name="shipping_cost_nonneg"),
        # Makes marketplace order imports idempotent.
        UniqueConstraint("marketplace_id", "external_order_id"),
        Index("ix_sales_user_id_sold_at", "user_id", "sold_at"),
        Index("ix_sales_item_id_user_id", "item_id", "user_id"),
        Index("ix_sales_listing_id", "listing_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Sale id={self.id} item={self.item_id} "
            f"x{self.quantity_sold} @{self.unit_price}>"
        )

"""PriceSnapshot — periodic market-price readings for a product.

This is the only append-only, fast-growing table in the schema: one row per
product per marketplace per poll. 500 products x 3 marketplaces x hourly is
~36,000 rows a day. So the indexing and the choice of key actually matter here,
where elsewhere they're mostly good hygiene.

Note there is NO user_id. Market price is shared reference data — see product.py.
Access control is implicit: a user only ever reaches snapshots through products
they own items for.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Money

if TYPE_CHECKING:
    from app.models.marketplace import Marketplace
    from app.models.product import Product


class PriceSnapshot(Base):
    """No TimestampMixin here.

    `captured_at` already records when the reading was taken, and created_at
    would be a near-duplicate of it. updated_at is meaningless for rows that
    are never updated. Skipping the mixin saves two columns and two index-less
    timestamps on the biggest table in the database — inheriting a mixin
    reflexively, without asking whether its columns mean anything, is a habit
    worth not forming.
    """

    __tablename__ = "price_snapshots"

    # BigInteger, not the usual int. A normal INTEGER primary key tops out at
    # ~2.1 billion. Every other table here would take decades to get near that;
    # this one is the plausible candidate, and running out of primary keys in
    # production is a famously bad afternoon. BIGINT costs 4 extra bytes a row.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE")
    )
    marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("marketplaces.id"), index=True
    )

    # All nullable: a given marketplace exposes some of these and not others.
    # StockX publishes asks and bids; eBay effectively only has sold prices.
    lowest_ask: Mapped[Money | None]
    highest_bid: Mapped[Money | None]
    last_sale: Mapped[Money | None]
    sales_volume_72h: Mapped[int | None]

    captured_at: Mapped[datetime]
    source: Mapped[str] = mapped_column(String(32))  # 'stockx_api', 'manual'

    product: Mapped["Product"] = relationship(back_populates="price_snapshots")
    marketplace: Mapped["Marketplace"] = relationship()

    __table_args__ = (
        # Makes the background poller IDEMPOTENT. Scheduled jobs get retried —
        # after a timeout, a redeploy mid-run, or two workers overlapping. This
        # constraint means a retry raises instead of quietly double-inserting and
        # skewing every average you compute later.
        UniqueConstraint("product_id", "marketplace_id", "captured_at"),
        # At least one price, or the row carries no information.
        CheckConstraint(
            "lowest_ask IS NOT NULL OR highest_bid IS NOT NULL OR last_sale IS NOT NULL",
            name="at_least_one_price",
        ),
    )

    def __repr__(self) -> str:
        return f"<PriceSnapshot product={self.product_id} at={self.captured_at}>"


# ---------------------------------------------------------------------------
# Declared OUTSIDE the class body, and that's necessary, not stylistic.
#
# Inside the class, `captured_at` is still a `mapped_column()` object — the
# descriptor that knows how to build a column — so `captured_at.desc()` is not
# available. Out here, after the class exists, `PriceSnapshot.captured_at` is a
# fully mapped attribute and `.desc()` works. The Index registers itself onto
# the table automatically just by being constructed.
#
# Why DESC here when items.py deliberately skipped it: this index has to serve
#
#     ORDER BY product_id, marketplace_id, captured_at DESC
#
# a MIXED-direction sort (two ascending, one descending). A backwards index scan
# reverses ALL columns at once, giving DESC/DESC/DESC — which is not what we
# asked for. So an all-ascending index cannot satisfy this ordering and Postgres
# would add a sort step. Declaring the direction here removes it.
#
# That ordering is the "latest price for each product" query, written with
# Postgres's DISTINCT ON, which pairs exactly with this index shape.
#
# The same index also serves, by the leftmost-prefix rule:
#   WHERE product_id = ?                          -> full chart for one product
#   WHERE product_id = ? AND marketplace_id = ?   -> one series
# It does NOT serve `WHERE marketplace_id = ?` alone — no leading prefix — which
# is fine, because nothing asks that question.
# ---------------------------------------------------------------------------
Index(
    "ix_price_snapshots_product_marketplace_captured",
    PriceSnapshot.product_id,
    PriceSnapshot.marketplace_id,
    PriceSnapshot.captured_at.desc(),
)

"""Listing — one lot offered for sale on one marketplace.

Why this table exists, when you could just put an `asking_price` on the item:

A single lot is often listed on eBay, StockX and Grailed simultaneously, at
three different prices. There is nowhere on the item row to put three prices.

The second reason matters more for the dashboard: listings that DIDN'T sell are
data. Sell-through rate ("what fraction of what I list actually sells?") and
time-to-sale per marketplace are only computable if you keep a record of the
attempts, not just the successes. Delete this table and those features become
impossible to build later.
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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Money, TimestampMixin
from app.models.enums import ListingStatus, sql_values

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.marketplace import Marketplace
    from app.models.sale import Sale


class Listing(TimestampMixin, Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Both of these are plain columns here, with NO ForeignKey() attached —
    # unusual, and deliberate. The relationship is declared as a COMPOSITE
    # foreign key in __table_args__ instead, because it spans two columns at
    # once and a per-column ForeignKey() cannot express that.
    user_id: Mapped[int]
    item_id: Mapped[int]

    marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("marketplaces.id"), index=True
    )

    asking_price: Mapped[Money]

    # A stored status column — unlike items, where it would be ambiguous. One
    # listing has exactly one lifecycle state at any moment, so an enum fits.
    status: Mapped[str] = mapped_column(
        String(16), server_default=text(f"'{ListingStatus.ACTIVE.value}'")
    )

    listed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # NULL while still active. Nullability comes from `| None` in the annotation —
    # you do NOT write `= None`, which SQLAlchemy would read as a mapper argument
    # rather than a default value.
    ended_at: Mapped[datetime | None]

    external_listing_id: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(500))

    item: Mapped["Item"] = relationship(back_populates="listings")
    marketplace: Mapped["Marketplace"] = relationship()
    sales: Mapped[list["Sale"]] = relationship(back_populates="listing")

    __table_args__ = (
        # ---- COMPOSITE FOREIGN KEY: tenancy enforced by the database ----
        # Points (item_id, user_id) at items(id, user_id) as a PAIR. This makes
        # a cross-tenant row physically unrepresentable: you cannot insert a
        # listing claiming user 4 owns item 9 if item 9 belongs to user 7 —
        # Postgres rejects it. A whole class of security bug becomes a
        # constraint violation. This is why items has UNIQUE (id, user_id).
        ForeignKeyConstraint(
            ["item_id", "user_id"],
            ["items.id", "items.user_id"],
            ondelete="CASCADE",
        ),
        # Target for the matching composite FK on sales — lets us guarantee a
        # sale's listing belongs to the same item as the sale. See sale.py.
        UniqueConstraint("id", "item_id"),
        CheckConstraint(f"status IN ({sql_values(ListingStatus)})", name="status_valid"),
        CheckConstraint("asking_price >= 0", name="asking_price_nonneg"),
        # Keeps two columns that encode the same fact from contradicting each
        # other. Reads as: "active" and "has no end date" must agree.
        #   active + ended_at NULL      -> TRUE = TRUE  -> ok
        #   ended + ended_at set        -> FALSE = FALSE -> ok
        #   active + ended_at set       -> TRUE = FALSE  -> REJECTED
        # In SQL, `=` between two booleans is a legal equivalence test.
        CheckConstraint(
            "(status = 'active') = (ended_at IS NULL)", name="ended_at_consistent"
        ),
        # ---- A business rule, enforced declaratively ----
        # "At most one ACTIVE listing per item per marketplace." A plain
        # UNIQUE (item_id, marketplace_id) would be wrong — it would stop you
        # ever relisting on eBay after an old listing ended. The partial WHERE
        # restricts the rule to active rows, so history accumulates freely.
        Index(
            "uq_listings_active_item_marketplace",
            "item_id",
            "marketplace_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        # "My active listings" page.
        Index("ix_listings_user_id_status", "user_id", "status"),
        # Indexes the composite FK's leading column, which Postgres does not do
        # for us, and which ON DELETE CASCADE needs to be fast.
        Index("ix_listings_item_id", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<Listing id={self.id} item={self.item_id} {self.status} @{self.asking_price}>"

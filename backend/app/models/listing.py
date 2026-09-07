"""Listing — one lot offered on one marketplace.

Separate from items because a lot can be listed on several marketplaces at
different prices, and unsold listings are needed for sell-through metrics.
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

    # No per-column ForeignKey: these are covered by the composite FK below.
    user_id: Mapped[int]
    item_id: Mapped[int]

    marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("marketplaces.id"), index=True
    )

    asking_price: Mapped[Money]
    status: Mapped[str] = mapped_column(
        String(16), server_default=text(f"'{ListingStatus.ACTIVE.value}'")
    )
    listed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None]

    external_listing_id: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(500))

    item: Mapped["Item"] = relationship(back_populates="listings")
    marketplace: Mapped["Marketplace"] = relationship()
    # overlaps: the composite FK below makes sales.item_id reachable from two
    # relationship paths. Intentional, and guarded by that FK.
    sales: Mapped[list["Sale"]] = relationship(
        back_populates="listing", overlaps="sales"
    )

    __table_args__ = (
        # Tenancy as a constraint: a listing cannot reference an item owned by a
        # different user, so cross-tenant rows are unrepresentable.
        ForeignKeyConstraint(
            ["item_id", "user_id"],
            ["items.id", "items.user_id"],
            ondelete="CASCADE",
        ),
        # Referent for the composite FK on sales.
        UniqueConstraint("id", "item_id"),
        CheckConstraint(f"status IN ({sql_values(ListingStatus)})", name="status_valid"),
        CheckConstraint("asking_price >= 0", name="asking_price_nonneg"),
        # Boolean equivalence: "is active" and "has no end date" must agree.
        CheckConstraint(
            "(status = 'active') = (ended_at IS NULL)", name="ended_at_consistent"
        ),
        # One active listing per item per marketplace; partial so relisting works.
        Index(
            "uq_listings_active_item_marketplace",
            "item_id",
            "marketplace_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_listings_user_id_status", "user_id", "status"),
        Index("ix_listings_item_id", "item_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Listing id={self.id} item={self.item_id} "
            f"{self.status} @{self.asking_price}>"
        )

"""PriceSnapshot — periodic market-price readings for a product.

Keyed on product rather than item so one reading serves every user holding it.
Append-only and the fastest-growing table, hence BigInteger and a covering
composite index.
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
    """No TimestampMixin: captured_at is the only timestamp that means anything."""

    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE")
    )
    marketplace_id: Mapped[int] = mapped_column(
        ForeignKey("marketplaces.id"), index=True
    )

    # Nullable individually: marketplaces expose different figures.
    lowest_ask: Mapped[Money | None]
    highest_bid: Mapped[Money | None]
    last_sale: Mapped[Money | None]
    sales_volume_72h: Mapped[int | None]

    captured_at: Mapped[datetime]
    source: Mapped[str] = mapped_column(String(32))

    product: Mapped["Product"] = relationship(back_populates="price_snapshots")
    marketplace: Mapped["Marketplace"] = relationship()

    __table_args__ = (
        # Makes a retried poll idempotent.
        UniqueConstraint("product_id", "marketplace_id", "captured_at"),
        CheckConstraint(
            "lowest_ask IS NOT NULL OR highest_bid IS NOT NULL OR last_sale IS NOT NULL",
            name="at_least_one_price",
        ),
    )

    def __repr__(self) -> str:
        return f"<PriceSnapshot product={self.product_id} at={self.captured_at}>"


# Declared outside the class so .desc() is available on the mapped attribute.
# DESC is required here: the latest-price query sorts product/marketplace
# ascending and captured_at descending, which a backwards index scan can't serve.
Index(
    "ix_price_snapshots_product_marketplace_captured",
    PriceSnapshot.product_id,
    PriceSnapshot.marketplace_id,
    PriceSnapshot.captured_at.desc(),
)

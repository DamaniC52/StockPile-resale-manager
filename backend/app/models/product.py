"""Product — shared catalog identity. GLOBAL data, not per-user data.

Why this table exists at all, since items already store a name and size:

Market price is a fact about *the product*, not about anyone's copy of it. If
five users each own the same Jordan 4 in size 10, the StockX lowest ask is one
number. Keying price history on `item_id` would store that number five times,
poll the API five times, and let the five copies drift apart.

So `products` is the thing prices hang off, and each user's `items` point at it.
Recognising which data is tenant-scoped and which is shared reference data is a
genuinely useful instinct — it's the same reasoning behind a `currencies` or
`countries` table.
"""

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ProductCategory, sql_values

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.price_snapshot import PriceSnapshot


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)

    brand: Mapped[str | None] = mapped_column(String(80))  # "Nike", "Supreme"
    name: Mapped[str] = mapped_column(String(200))  # "Air Jordan 4 Retro Bred"
    # Manufacturer style code — "DZ5485-612". The closest thing sneakers have to
    # a universal identifier, which is why it anchors the uniqueness rule below.
    sku: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(
        String(32), server_default=text(f"'{ProductCategory.OTHER.value}'")
    )

    items: Mapped[list["Item"]] = relationship(back_populates="product")
    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # A product is identified by style code + size: the same shoe in size 9
        # and size 10 are different products with different market prices.
        #
        # postgresql_nulls_not_distinct is the interesting part. By DEFAULT, SQL
        # treats NULL as "unknown", so NULL != NULL, and a plain UNIQUE(sku, size)
        # would happily accept a thousand rows with sku = NULL. That silently
        # breaks dedup for exactly the messy records you most want deduped.
        #
        # NULLS NOT DISTINCT (Postgres 15+) makes NULL compare equal to NULL for
        # this constraint, so at most one (NULL, NULL) row can exist.
        UniqueConstraint("sku", "size", postgresql_nulls_not_distinct=True),
        CheckConstraint(
            f"category IN ({sql_values(ProductCategory)})", name="category_valid"
        ),
        # Serves the catalog picker's "type a brand, see its products" lookup.
        Index("ix_products_brand_name", "brand", "name"),
    )

    def __repr__(self) -> str:
        return f"<Product {self.brand} {self.name!r} size={self.size}>"

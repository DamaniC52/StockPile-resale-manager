"""Product — shared catalog identity that market prices attach to.

Global, not per-user: five users owning the same shoe share one market price.
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
    brand: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str | None] = mapped_column(String(64))  # style code, e.g. DZ5485-612
    size: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(
        String(32), server_default=text(f"'{ProductCategory.OTHER.value}'")
    )

    items: Mapped[list["Item"]] = relationship(back_populates="product")
    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # NULLS NOT DISTINCT (PG15+): without it, NULL != NULL and rows with a
        # missing sku would never be treated as duplicates.
        UniqueConstraint("sku", "size", postgresql_nulls_not_distinct=True),
        CheckConstraint(
            f"category IN ({sql_values(ProductCategory)})", name="category_valid"
        ),
        Index("ix_products_brand_name", "brand", "name"),
    )

    def __repr__(self) -> str:
        return f"<Product {self.brand} {self.name!r} size={self.size}>"

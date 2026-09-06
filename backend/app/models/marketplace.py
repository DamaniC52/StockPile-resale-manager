"""Marketplaces (eBay, StockX, ...) — global reference data, not user data.

This is a *lookup table*. Note what we did NOT do: store the marketplace as a
free-text string on every sale. That would allow "eBay", "ebay", "Ebay", and
"eaby" to coexist, and "profit by marketplace" would then silently split one
platform across four rows. A foreign key to a lookup table makes that
impossible — the classic argument for normalisation.
"""

from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Marketplace(TimestampMixin, Base):
    __tablename__ = "marketplaces"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(60))  # "StockX" — for display
    # URL-safe stable identifier. Frontend code and seed scripts reference the
    # slug rather than the integer id, because ids differ between your local
    # database and production while slugs don't.
    slug: Mapped[str] = mapped_column(String(40), unique=True)

    # Typical seller fee as a fraction (0.1250 = 12.5%). Used only to PRE-FILL
    # the fee field in the sale form as a convenience. The actual fee charged is
    # always stored on the sale itself, because real fees vary by seller level,
    # promotions, and category. Never compute historical profit from this column.
    # Mapped[Decimal] = the PYTHON type. Numeric(5, 4) = the POSTGRES type.
    # `| None` is what makes the column NULLABLE — SQLAlchemy reads nullability
    # straight off the annotation, which is why you rarely write nullable=True.
    default_fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))

    is_active: Mapped[bool] = mapped_column(server_default="true")

    __table_args__ = (
        CheckConstraint(
            "default_fee_pct IS NULL OR (default_fee_pct >= 0 AND default_fee_pct < 1)",
            name="fee_pct_fraction",
        ),
    )

    def __repr__(self) -> str:
        return f"<Marketplace {self.slug}>"

"""Marketplaces (eBay, StockX, ...) — global reference data."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Marketplace(TimestampMixin, Base):
    __tablename__ = "marketplaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    slug: Mapped[str] = mapped_column(String(40), unique=True)

    # Pre-fills the sale form only. Actual fees are recorded per sale.
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

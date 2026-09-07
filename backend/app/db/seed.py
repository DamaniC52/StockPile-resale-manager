"""Seed marketplace reference data.

Run with: .venv/Scripts/python -m app.db.seed

Kept out of migrations so it stays editable, and idempotent so it can run on
every deploy without creating duplicates.
"""

from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal
from app.models.marketplace import Marketplace

# Rough defaults that pre-fill the sale form; real fees are recorded per sale.
MARKETPLACES = [
    {"slug": "stockx", "name": "StockX", "default_fee_pct": Decimal("0.0900")},
    {"slug": "ebay", "name": "eBay", "default_fee_pct": Decimal("0.1325")},
    {"slug": "goat", "name": "GOAT", "default_fee_pct": Decimal("0.0950")},
    {"slug": "depop", "name": "Depop", "default_fee_pct": Decimal("0.1000")},
    {"slug": "grailed", "name": "Grailed", "default_fee_pct": Decimal("0.0900")},
    # Sentinel for off-platform sales, so sales.marketplace_id stays NOT NULL.
    {"slug": "direct", "name": "Direct / Cash", "default_fee_pct": Decimal("0.0000")},
]


def seed_marketplaces() -> int:
    """Insert missing marketplaces; returns the number added."""
    with SessionLocal() as session:
        stmt = (
            insert(Marketplace)
            .values(MARKETPLACES)
            .on_conflict_do_nothing(index_elements=["slug"])
            # RETURNING rather than rowcount, which reports -1 for multi-row
            # ON CONFLICT DO NOTHING.
            .returning(Marketplace.slug)
        )
        inserted = session.scalars(stmt).all()
        session.commit()
        return len(inserted)


if __name__ == "__main__":
    added = seed_marketplaces()
    print(f"marketplaces: {added} inserted, {len(MARKETPLACES) - added} already present")

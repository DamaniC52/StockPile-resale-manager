"""Domain enumerations.

Columns using these are String + CHECK rather than native Postgres ENUM:
values can't be removed from a PG enum, and ALTER TYPE fights Alembic.
"""

from enum import StrEnum


class ItemCondition(StrEnum):
    NEW = "new"
    LIKE_NEW = "like_new"
    USED = "used"
    DAMAGED = "damaged"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    SOLD = "sold"
    ENDED = "ended"


class StockStatus(StrEnum):
    """Derived from quantity vs. quantity_remaining; never stored."""

    IN_STOCK = "in_stock"
    PARTIALLY_SOLD = "partially_sold"
    SOLD_OUT = "sold_out"


class ProductCategory(StrEnum):
    SNEAKERS = "sneakers"
    STREETWEAR = "streetwear"
    COLLECTIBLE = "collectible"
    ACCESSORY = "accessory"
    OTHER = "other"


def sql_values(enum_cls: type[StrEnum]) -> str:
    """Render an enum as a SQL value list, e.g. `'new','used'`."""
    return ",".join(f"'{member.value}'" for member in enum_cls)

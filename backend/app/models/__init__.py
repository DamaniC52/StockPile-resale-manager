"""Model registry.

Importing every model here is required for Alembic autogenerate: a model only
enters Base.metadata when its module is imported.
"""

from app.models.enums import (
    ItemCondition,
    ListingStatus,
    ProductCategory,
    StockStatus,
)
from app.models.item import Item
from app.models.listing import Listing
from app.models.marketplace import Marketplace
from app.models.price_snapshot import PriceSnapshot
from app.models.product import Product
from app.models.sale import Sale
from app.models.user import User

__all__ = [
    "Item",
    "ItemCondition",
    "Listing",
    "ListingStatus",
    "Marketplace",
    "PriceSnapshot",
    "Product",
    "ProductCategory",
    "Sale",
    "StockStatus",
    "User",
]

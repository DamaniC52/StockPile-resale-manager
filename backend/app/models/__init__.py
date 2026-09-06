"""Model package — and the single place that imports every model.

This file is load-bearing for Alembic, not just tidiness.

Alembic's `--autogenerate` compares the live database against
`Base.metadata`. But a model only registers itself in that metadata when its
module is actually IMPORTED. A model you never import is invisible, so Alembic
concludes the table shouldn't exist — and generates a migration that silently
omits it, or worse, drops it.

Importing everything here, and having alembic/env.py import this package, makes
"did I remember to register the model?" a non-question.

The `__all__` list also silences linters that would otherwise flag these as
unused imports.
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

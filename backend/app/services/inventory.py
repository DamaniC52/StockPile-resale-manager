"""Inventory write operations.

Lives in a service rather than the router because creating a lot has an
invariant the router shouldn't own: quantity_remaining must start equal to
quantity. Any second caller (a CSV importer) must get that for free.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.product import Product
from app.schemas.item import ItemCreate, ItemUpdate


class InvalidProduct(Exception):
    """A referenced product does not exist."""


class QuantityBelowSold(Exception):
    """Reducing quantity below the number already sold."""

    def __init__(self, sold: int) -> None:
        self.sold = sold
        super().__init__(f"{sold} units already sold")


def _require_product(db: Session, product_id: int | None) -> None:
    if product_id is None:
        return
    # Checked here so a bad id becomes a 400 rather than a raw IntegrityError.
    if db.scalar(select(Product.id).where(Product.id == product_id)) is None:
        raise InvalidProduct


def create_lot(db: Session, *, user_id: int, payload: ItemCreate) -> Item:
    """Create a lot with nothing sold yet."""
    _require_product(db, payload.product_id)

    item = Item(
        user_id=user_id,
        # The invariant: a new lot has sold nothing, so remaining == quantity.
        quantity_remaining=payload.quantity,
        **payload.model_dump(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_lot(db: Session, *, item: Item, payload: ItemUpdate) -> Item:
    """Apply a partial update to a lot.

    Editing unit_cost is not retroactive: sales carry their own cost snapshot,
    so past profit figures are unaffected by design.
    """
    # exclude_unset distinguishes "field omitted" from "field explicitly null",
    # which is the whole basis of PATCH semantics. Without it, every absent
    # field would arrive as None and blank the stored value.
    changes = payload.model_dump(exclude_unset=True)

    if "product_id" in changes:
        _require_product(db, changes["product_id"])

    for field, value in changes.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)
    return item


def adjust_quantity(db: Session, *, item: Item, new_quantity: int) -> Item:
    """Correct a miscounted lot size, preserving units already sold.

    Kept separate from update_lot because quantity and quantity_remaining must
    move together, and the floor depends on how much has already sold.
    """
    sold = item.quantity - item.quantity_remaining
    if new_quantity < sold:
        raise QuantityBelowSold(sold)

    item.quantity = new_quantity
    item.quantity_remaining = new_quantity - sold
    db.commit()
    db.refresh(item)
    return item

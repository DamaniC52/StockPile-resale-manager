"""Sale recording — the only place inventory quantity is allowed to change.

Two invariants live here and nowhere else:

1. A sale can never consume more units than the lot has left, even under
   concurrent requests.
2. A lot's flat acquisition fee is divided across its sales so the parts sum to
   exactly the original total, with no cent lost to rounding.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.listing import Listing
from app.models.sale import Sale

if TYPE_CHECKING:
    from app.schemas.sale import SaleCreate

CENTS = Decimal("0.01")


class ItemNotFound(Exception):
    """No such item, or it belongs to another user."""


class InsufficientQuantity(Exception):
    def __init__(self, available: int, requested: int) -> None:
        self.available = available
        self.requested = requested
        super().__init__(f"only {available} of {requested} units available")


class ListingNotForItem(Exception):
    """The listing belongs to a different item."""


def allocate_acquisition_fee(
    *,
    fee_total: Decimal,
    quantity: int,
    quantity_sold: int,
    remaining_after: int,
    already_allocated: Decimal,
) -> Decimal:
    """This sale's share of the lot's flat acquisition fee.

    Proportional shares are rounded to cents, which means they generally do not
    sum to the total. The final sale of the lot therefore absorbs whatever is
    left over, making the sum exact by construction rather than by luck.
    """
    if fee_total == 0:
        return Decimal("0")
    if remaining_after == 0:
        return fee_total - already_allocated
    share = fee_total * Decimal(quantity_sold) / Decimal(quantity)
    return share.quantize(CENTS, rounding=ROUND_HALF_UP)


def record_sale(db: Session, *, user_id: int, payload: "SaleCreate") -> Sale:
    """Record a sale and decrement the lot, atomically."""
    # One statement does the ownership check, the stock check, and the
    # decrement. Because the WHERE clause includes the quantity test, Postgres
    # locks the row and re-evaluates that test against the committed-current
    # version, so two concurrent sales cannot both pass it. A read-then-write
    # in Python would have a window between the check and the update.
    #
    # Zero rows updated is the rejection signal.
    stmt = (
        update(Item)
        .where(
            Item.id == payload.item_id,
            Item.user_id == user_id,
            Item.quantity_remaining >= payload.quantity_sold,
        )
        .values(quantity_remaining=Item.quantity_remaining - payload.quantity_sold)
        .returning(
            Item.quantity,
            Item.quantity_remaining,
            Item.unit_cost,
            Item.acquisition_fee_total,
        )
    )
    lot = db.execute(stmt).one_or_none()

    if lot is None:
        db.rollback()
        # Only on the failure path do we spend a query working out which of the
        # two reasons applied, so the success path stays a single round trip.
        available = db.scalar(
            select(Item.quantity_remaining).where(
                Item.id == payload.item_id, Item.user_id == user_id
            )
        )
        if available is None:
            raise ItemNotFound
        raise InsufficientQuantity(available=available, requested=payload.quantity_sold)

    if payload.listing_id is not None:
        # Validated here for a clean error; the composite FK on
        # (listing_id, item_id) is the actual guarantee.
        owner = db.scalar(
            select(Listing.item_id).where(Listing.id == payload.listing_id)
        )
        if owner != payload.item_id:
            db.rollback()
            raise ListingNotForItem

    # Safe to read without extra locking: the successful UPDATE above holds this
    # item's row lock until commit, so no competing sale of the same lot can be
    # interleaved with this sum.
    already = db.scalar(
        select(func.coalesce(func.sum(Sale.acq_fee_allocated), Decimal("0"))).where(
            Sale.item_id == payload.item_id
        )
    ) or Decimal("0")

    sale = Sale(
        user_id=user_id,
        unit_cost_snapshot=lot.unit_cost,
        acq_fee_allocated=allocate_acquisition_fee(
            fee_total=lot.acquisition_fee_total,
            quantity=lot.quantity,
            quantity_sold=payload.quantity_sold,
            remaining_after=lot.quantity_remaining,
            already_allocated=already,
        ),
        **payload.model_dump(),
    )
    db.add(sale)
    # The decrement and the insert commit together or not at all.
    db.commit()
    db.refresh(sale)
    return sale


def void_sale(db: Session, *, sale: Sale) -> None:
    """Reverse a sale, returning its units to the lot."""
    db.execute(
        update(Item)
        .where(Item.id == sale.item_id, Item.user_id == sale.user_id)
        .values(quantity_remaining=Item.quantity_remaining + sale.quantity_sold)
    )
    db.delete(sale)
    db.commit()

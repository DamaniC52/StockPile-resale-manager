"""Partial sales, fee allocation, and profit arithmetic."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.sale import Sale
from app.schemas.sale import SaleCreate
from app.services import sales as svc


def sale_payload(item_id: int, marketplace_id: int, **kw) -> SaleCreate:
    defaults = dict(
        item_id=item_id,
        marketplace_id=marketplace_id,
        quantity_sold=1,
        unit_price=Decimal("200.00"),
        sold_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    return SaleCreate(**{**defaults, **kw})


def test_partial_sale_decrements_lot(db: Session, user, marketplace, lot):
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=2)
    )
    db.refresh(lot)
    assert lot.quantity == 3
    assert lot.quantity_remaining == 1
    assert lot.stock_status == "partially_sold"


def test_selling_out_sets_status(db: Session, user, marketplace, lot):
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=3)
    )
    db.refresh(lot)
    assert lot.quantity_remaining == 0
    assert lot.stock_status == "sold_out"


def test_oversell_is_rejected(db: Session, user, marketplace, lot):
    with pytest.raises(svc.InsufficientQuantity) as exc:
        svc.record_sale(
            db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=4)
        )
    assert exc.value.available == 3
    db.refresh(lot)
    # The failed attempt must not have consumed anything.
    assert lot.quantity_remaining == 3


def test_other_users_item_is_not_found(db: Session, user, marketplace, lot):
    with pytest.raises(svc.ItemNotFound):
        svc.record_sale(
            db, user_id=user.id + 999, payload=sale_payload(lot.id, marketplace.id)
        )


def test_fee_allocation_sums_to_exactly_the_total(db: Session, user, marketplace, lot):
    """$20 across 3 units is $6.6667 each; the parts must still total $20.00."""
    for _ in range(3):
        svc.record_sale(
            db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=1)
        )

    allocated = db.scalars(
        select(Sale.acq_fee_allocated).where(Sale.item_id == lot.id).order_by(Sale.id)
    ).all()

    # First two take the rounded proportional share, the last absorbs the rest.
    assert allocated == [Decimal("6.67"), Decimal("6.67"), Decimal("6.66")]
    assert sum(allocated) == Decimal("20.00")


def test_fee_allocation_exact_across_uneven_splits(db: Session, user, marketplace, lot):
    """A 2-then-1 split must also total exactly $20.00."""
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=2)
    )
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=1)
    )
    total = db.scalar(
        select(func.sum(Sale.acq_fee_allocated)).where(Sale.item_id == lot.id)
    )
    assert total == Decimal("20.00")


def test_cost_basis_is_snapshotted(db: Session, user, marketplace, lot):
    """Editing the item's cost later must not change a recorded sale."""
    sale = svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id)
    )
    original_profit = sale.net_profit

    lot.unit_cost = Decimal("999.00")
    db.commit()

    db.refresh(sale)
    assert sale.unit_cost_snapshot == Decimal("60.00")
    assert sale.net_profit == original_profit


def test_profit_arithmetic(db: Session, user, marketplace, lot):
    sale = svc.record_sale(
        db,
        user_id=user.id,
        payload=sale_payload(
            lot.id,
            marketplace.id,
            quantity_sold=2,
            unit_price=Decimal("200.00"),
            platform_fee=Decimal("36.00"),
            shipping_cost=Decimal("15.00"),
        ),
    )
    # revenue 400.00
    # cogs    60*2 + 13.33 (rounded 2/3 share of 20) = 133.33
    # profit  400 - 36 - 15 - 0 - 133.33 = 215.67
    assert sale.revenue == Decimal("400.00")
    assert sale.cogs == Decimal("133.33")
    assert sale.net_profit == Decimal("215.67")


def test_net_profit_aggregates_in_sql(db: Session, user, marketplace, lot):
    """The hybrid must compile to SQL, not just work on instances."""
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=1)
    )
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=1)
    )

    # Computed by Postgres. This only compiles because of @net_profit.expression.
    total = db.scalar(
        select(func.sum(Sale.net_profit)).where(Sale.user_id == user.id)
    )
    in_python = sum(
        s.net_profit for s in db.scalars(select(Sale).where(Sale.user_id == user.id))
    )
    assert total == in_python


def test_loss_is_allowed(db: Session, user, marketplace, lot):
    """Selling below cost is a real outcome, not a validation error."""
    sale = svc.record_sale(
        db,
        user_id=user.id,
        payload=sale_payload(lot.id, marketplace.id, unit_price=Decimal("10.00")),
    )
    assert sale.net_profit < 0


def test_void_returns_units_to_the_lot(db: Session, user, marketplace, lot):
    sale = svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=2)
    )
    db.refresh(lot)
    assert lot.quantity_remaining == 1

    svc.void_sale(db, sale=sale)
    db.refresh(lot)
    assert lot.quantity_remaining == 3
    assert db.scalar(select(func.count()).select_from(Sale)) == 0


def test_quantity_remaining_never_drifts(db: Session, user, marketplace, lot):
    """The denormalized counter must always equal quantity minus units sold."""
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=2)
    )
    svc.record_sale(
        db, user_id=user.id, payload=sale_payload(lot.id, marketplace.id, quantity_sold=1)
    )

    computed = db.scalar(
        select(
            Item.quantity
            - func.coalesce(
                select(func.sum(Sale.quantity_sold))
                .where(Sale.item_id == Item.id)
                .scalar_subquery(),
                0,
            )
        ).where(Item.id == lot.id)
    )
    db.refresh(lot)
    assert lot.quantity_remaining == computed

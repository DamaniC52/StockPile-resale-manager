"""Two simultaneous sales of the last units must not both succeed.

This is the test the quantity design exists for. A read-then-write in Python
passes every single-threaded test above and still oversells under load, so
correctness here can only be shown with two connections genuinely racing.
"""

from datetime import datetime, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.models.item import Item
from app.models.sale import Sale
from app.schemas.sale import SaleCreate
from app.services import sales as svc


def _attempt(session_factory, user_id: int, item_id: int, marketplace_id: int, qty: int):
    """Run record_sale on its own session and connection."""
    payload = SaleCreate(
        item_id=item_id,
        marketplace_id=marketplace_id,
        quantity_sold=qty,
        unit_price=Decimal("200.00"),
        sold_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    with session_factory() as session:
        try:
            svc.record_sale(session, user_id=user_id, payload=payload)
            return "sold"
        except svc.InsufficientQuantity:
            return "rejected"


def test_two_concurrent_sales_of_the_last_unit(
    db, session_factory, user, marketplace, lot
):
    """With 1 unit left, two simultaneous buyers: exactly one wins."""
    # Consume 2 of 3 so a single unit remains.
    svc.record_sale(
        db,
        user_id=user.id,
        payload=SaleCreate(
            item_id=lot.id,
            marketplace_id=marketplace.id,
            quantity_sold=2,
            unit_price=Decimal("200.00"),
            sold_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ),
    )
    db.commit()

    # Two real threads, two connections, contending for the same row.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_attempt, session_factory, user.id, lot.id, marketplace.id, 1)
            for _ in range(2)
        ]
        outcomes = sorted(f.result() for f in futures)

    assert outcomes == ["rejected", "sold"], f"expected one of each, got {outcomes}"

    db.expire_all()
    remaining = db.scalar(select(Item.quantity_remaining).where(Item.id == lot.id))
    units_sold = db.scalar(
        select(func.coalesce(func.sum(Sale.quantity_sold), 0)).where(Sale.item_id == lot.id)
    )
    assert remaining == 0
    assert units_sold == 3, "never more units sold than the lot ever held"


def test_many_concurrent_sales_cannot_oversell(
    db, session_factory, user, marketplace, lot
):
    """8 threads race for 3 units: exactly 3 succeed, and the lot ends at 0."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(_attempt, session_factory, user.id, lot.id, marketplace.id, 1)
            for _ in range(8)
        ]
        outcomes = [f.result() for f in futures]

    assert outcomes.count("sold") == 3
    assert outcomes.count("rejected") == 5

    db.expire_all()
    assert db.scalar(select(Item.quantity_remaining).where(Item.id == lot.id)) == 0
    assert (
        db.scalar(select(func.sum(Sale.quantity_sold)).where(Sale.item_id == lot.id)) == 3
    )


def test_fee_allocation_stays_exact_under_concurrency(
    db, session_factory, user, marketplace, lot
):
    """Even when sales race, allocated fees must total exactly $20.00.

    Guarded by the row lock the successful UPDATE holds: sales of one lot are
    serialized, so the running SUM the allocator reads is never stale.
    """
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [
            pool.submit(_attempt, session_factory, user.id, lot.id, marketplace.id, 1)
            for _ in range(5)
        ]
        [f.result() for f in futures]

    db.expire_all()
    total = db.scalar(
        select(func.sum(Sale.acq_fee_allocated)).where(Sale.item_id == lot.id)
    )
    assert total == Decimal("20.00"), f"fees drifted to {total}"

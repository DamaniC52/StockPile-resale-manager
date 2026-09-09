"""Dashboard aggregations.

Every function returns rows, not ORM objects: these are reports, not entities.
All arithmetic happens in Postgres so the API returns a handful of numbers
rather than the sales that produced them.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.marketplace import Marketplace
from app.models.sale import Sale

Bucket = Literal["day", "week", "month"]

ZERO = Decimal("0")


def _scoped(stmt: Select, user_id: int) -> Select:
    """Apply tenant scoping. Every query here goes through it."""
    return stmt.where(Sale.user_id == user_id)


def profit_summary(
    session: Session,
    *,
    user_id: int,
    since: datetime | None = None,
) -> dict:
    """Headline figures: realized profit, revenue, fees, units sold.

    One row out of the database regardless of how many sales exist. The SUMs
    compile from the hybrid properties on Sale, so the formula is defined once
    and evaluated here in SQL.
    """
    stmt = _scoped(
        select(
            func.count(Sale.id).label("sale_count"),
            func.coalesce(func.sum(Sale.quantity_sold), 0).label("units_sold"),
            func.coalesce(func.sum(Sale.revenue), ZERO).label("revenue"),
            func.coalesce(func.sum(Sale.cogs), ZERO).label("cogs"),
            func.coalesce(
                func.sum(Sale.platform_fee + Sale.shipping_cost + Sale.other_fees), ZERO
            ).label("fees"),
            func.coalesce(func.sum(Sale.net_profit), ZERO).label("net_profit"),
        ),
        user_id,
    )
    if since is not None:
        stmt = stmt.where(Sale.sold_at >= since)

    row = session.execute(stmt).one()
    return dict(row._mapping)


def inventory_summary(session: Session, *, user_id: int) -> dict:
    """Capital currently tied up in unsold stock.

    Reads items rather than sales, so it is a separate query — combining them
    would need a join that multiplies rows and inflates the sums.
    """
    stmt = select(
        func.count(Item.id).label("lot_count"),
        func.coalesce(func.sum(Item.quantity_remaining), 0).label("units_in_stock"),
        func.coalesce(
            func.sum(Item.unit_cost * Item.quantity_remaining), ZERO
        ).label("capital_tied_up"),
    ).where(Item.user_id == user_id)

    row = session.execute(stmt).one()
    return dict(row._mapping)


def profit_over_time(
    session: Session,
    *,
    user_id: int,
    bucket: Bucket = "month",
    since: datetime | None = None,
) -> list[dict]:
    """Profit grouped into time buckets.

    `date_trunc` rounds a timestamp down to the start of its period, which is
    what turns individual sales into a chartable series. Grouping on the same
    expression that is selected is what makes the aggregate legal.
    """
    period = func.date_trunc(bucket, Sale.sold_at).label("period")

    stmt = _scoped(
        select(
            period,
            func.count(Sale.id).label("sale_count"),
            func.coalesce(func.sum(Sale.quantity_sold), 0).label("units_sold"),
            func.coalesce(func.sum(Sale.revenue), ZERO).label("revenue"),
            func.coalesce(func.sum(Sale.cogs), ZERO).label("cogs"),
            func.coalesce(func.sum(Sale.net_profit), ZERO).label("net_profit"),
        ),
        user_id,
    ).group_by(period).order_by(period)

    if since is not None:
        stmt = stmt.where(Sale.sold_at >= since)

    return [dict(r._mapping) for r in session.execute(stmt)]


def profit_by_marketplace(session: Session, *, user_id: int) -> list[dict]:
    """Which platforms actually make money after their fees.

    The join is to marketplaces for the display name only; the grouping key is
    the id denormalized onto sales, so no join is needed for correctness.
    """
    stmt = (
        _scoped(
            select(
                Marketplace.name.label("marketplace"),
                Marketplace.slug.label("slug"),
                func.count(Sale.id).label("sale_count"),
                func.coalesce(func.sum(Sale.revenue), ZERO).label("revenue"),
                func.coalesce(func.sum(Sale.platform_fee), ZERO).label("platform_fees"),
                func.coalesce(func.sum(Sale.net_profit), ZERO).label("net_profit"),
            ),
            user_id,
        )
        .join(Marketplace, Marketplace.id == Sale.marketplace_id)
        .group_by(Marketplace.id, Marketplace.name, Marketplace.slug)
        .order_by(func.sum(Sale.net_profit).desc())
    )
    return [dict(r._mapping) for r in session.execute(stmt)]


# Bucket boundaries in days. Held stock loses value the longer it sits, so the
# question is "how much capital is stale", not "how old is each lot".
AGING_BUCKETS = ((30, "0-30 days"), (60, "31-60 days"), (90, "61-90 days"))


def inventory_aging(session: Session, *, user_id: int) -> list[dict]:
    """Unsold capital grouped by how long it has been held.

    The CASE is built from AGING_BUCKETS so the labels and the boundaries
    cannot drift apart.
    """
    age_days = func.current_date() - Item.purchased_at

    whens = [(age_days <= days, label) for days, label in AGING_BUCKETS]
    bucket = case(*whens, else_="90+ days").label("bucket")

    # Sorts the buckets by their boundary rather than alphabetically, which
    # would put "0-30" after "31-60".
    order = case(
        *[(age_days <= days, i) for i, (days, _) in enumerate(AGING_BUCKETS)],
        else_=len(AGING_BUCKETS),
    )

    stmt = (
        select(
            bucket,
            func.count(Item.id).label("lot_count"),
            func.coalesce(func.sum(Item.quantity_remaining), 0).label("units"),
            func.coalesce(
                func.sum(Item.unit_cost * Item.quantity_remaining), ZERO
            ).label("capital"),
        )
        .where(Item.user_id == user_id, Item.quantity_remaining > 0)
        .group_by(bucket, order)
        .order_by(order)
    )
    return [dict(r._mapping) for r in session.execute(stmt)]


def top_items(session: Session, *, user_id: int, limit: int = 5) -> list[dict]:
    """Best and worst performing lots by realized profit."""
    stmt = (
        _scoped(
            select(
                Item.id.label("item_id"),
                Item.name.label("name"),
                Item.size.label("size"),
                func.coalesce(func.sum(Sale.quantity_sold), 0).label("units_sold"),
                func.coalesce(func.sum(Sale.net_profit), ZERO).label("net_profit"),
            ),
            user_id,
        )
        .join(Item, Item.id == Sale.item_id)
        .group_by(Item.id, Item.name, Item.size)
        .order_by(func.sum(Sale.net_profit).desc())
        .limit(limit)
    )
    return [dict(r._mapping) for r in session.execute(stmt)]


def first_sale_date(session: Session, *, user_id: int) -> date | None:
    """Earliest sale, so the client can size a chart's axis without fetching rows."""
    return session.scalar(
        _scoped(select(func.min(Sale.sold_at)), user_id)
    )

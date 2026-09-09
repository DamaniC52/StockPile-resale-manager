"""Dashboard endpoints. Read-only aggregations over the caller's own data."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.queries import dashboard as q

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Range = Literal["1m", "3m", "6m", "1y", "ytd", "all"]

_DAYS = {"1m": 30, "3m": 90, "6m": 182, "1y": 365}


def _since(range_: Range) -> datetime | None:
    """Resolve a range name to a cutoff. None means no lower bound."""
    if range_ == "all":
        return None
    now = datetime.now(timezone.utc)
    if range_ == "ytd":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=_DAYS[range_])


class Summary(BaseModel):
    sale_count: int
    units_sold: int
    revenue: Decimal
    cogs: Decimal
    fees: Decimal
    net_profit: Decimal
    # Profit inside the selected window, for the change indicator.
    period_net_profit: Decimal
    period_sale_count: int
    lot_count: int
    units_in_stock: int
    capital_tied_up: Decimal


class TimePoint(BaseModel):
    period: datetime
    sale_count: int
    units_sold: int
    revenue: Decimal
    cogs: Decimal
    net_profit: Decimal


class MarketplaceRow(BaseModel):
    marketplace: str
    slug: str
    sale_count: int
    revenue: Decimal
    platform_fees: Decimal
    net_profit: Decimal


class AgingRow(BaseModel):
    bucket: str
    lot_count: int
    units: int
    capital: Decimal


class TopItem(BaseModel):
    item_id: int
    name: str
    size: str | None
    units_sold: int
    net_profit: Decimal


@router.get("/summary", response_model=Summary)
def summary(db: DbSession, user: CurrentUser, range: Range = "all") -> Summary:
    """Headline figures, lifetime and windowed.

    Lifetime totals and the windowed figure come from two calls rather than one
    so the client can show "up $x this month" against an all-time total without
    doing arithmetic the database already did.
    """
    lifetime = q.profit_summary(db, user_id=user.id)
    windowed = q.profit_summary(db, user_id=user.id, since=_since(range))
    stock = q.inventory_summary(db, user_id=user.id)

    return Summary(
        **lifetime,
        period_net_profit=windowed["net_profit"],
        period_sale_count=windowed["sale_count"],
        **stock,
    )


@router.get("/profit-over-time", response_model=list[TimePoint])
def profit_over_time(
    db: DbSession,
    user: CurrentUser,
    range: Range = "all",
    bucket: q.Bucket = "month",
) -> list[dict]:
    return q.profit_over_time(
        db, user_id=user.id, bucket=bucket, since=_since(range)
    )


@router.get("/by-marketplace", response_model=list[MarketplaceRow])
def by_marketplace(db: DbSession, user: CurrentUser) -> list[dict]:
    return q.profit_by_marketplace(db, user_id=user.id)


@router.get("/inventory-aging", response_model=list[AgingRow])
def inventory_aging(db: DbSession, user: CurrentUser) -> list[dict]:
    return q.inventory_aging(db, user_id=user.id)


@router.get("/top-items", response_model=list[TopItem])
def top_items(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=5, ge=1, le=25),
) -> list[dict]:
    return q.top_items(db, user_id=user.id, limit=limit)

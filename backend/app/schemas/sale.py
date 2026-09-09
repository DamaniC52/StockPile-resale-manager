"""Request and response schemas for sales."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SaleCreate(BaseModel):
    item_id: int
    marketplace_id: int
    quantity_sold: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    sold_at: datetime

    listing_id: int | None = None
    platform_fee: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    shipping_cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    other_fees: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    payout_at: datetime | None = None
    external_order_id: str | None = Field(default=None, max_length=64)


class ItemRef(BaseModel):
    """Just enough of the lot to label a sale."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    size: str | None


class MarketplaceRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class SaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    listing_id: int | None
    marketplace_id: int
    quantity_sold: int
    unit_price: Decimal
    platform_fee: Decimal
    shipping_cost: Decimal
    other_fees: Decimal
    unit_cost_snapshot: Decimal
    acq_fee_allocated: Decimal
    sold_at: datetime
    payout_at: datetime | None
    external_order_id: str | None

    # Read off the hybrid properties; computed in Python here, in SQL when
    # aggregated by the dashboard.
    revenue: Decimal
    cogs: Decimal
    net_profit: Decimal

    # Populated from the relationships. list_sales eager-loads both; without
    # that, serializing a page of 20 sales would fire 40 extra queries.
    item: ItemRef
    marketplace: MarketplaceRef


class SaleListResponse(BaseModel):
    sales: list[SaleRead]
    total: int
    limit: int
    offset: int

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


class SaleListResponse(BaseModel):
    sales: list[SaleRead]
    total: int
    limit: int
    offset: int

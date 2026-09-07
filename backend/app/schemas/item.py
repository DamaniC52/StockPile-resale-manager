"""Request and response schemas for inventory items."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ItemCondition, StockStatus


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0)
    unit_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    purchased_at: date

    size: str | None = Field(default=None, max_length=20)
    condition: ItemCondition = ItemCondition.NEW
    acquisition_fee_total: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=12, decimal_places=2
    )
    product_id: int | None = None
    source: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class ItemUpdate(BaseModel):
    """All fields optional: absent means "leave unchanged".

    `quantity_remaining` is deliberately absent — it is owned by the sales
    service, and letting clients set it directly would break the link between
    recorded sales and remaining stock.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    size: str | None = Field(default=None, max_length=20)
    condition: ItemCondition | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    acquisition_fee_total: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    purchased_at: date | None = None
    product_id: int | None = None
    source: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    size: str | None
    condition: ItemCondition
    quantity: int
    quantity_remaining: int
    unit_cost: Decimal
    acquisition_fee_total: Decimal
    purchased_at: date
    product_id: int | None
    source: str | None
    notes: str | None
    created_at: datetime

    # Read off the hybrid property on the model; no extra query.
    stock_status: StockStatus


class ItemListResponse(BaseModel):
    """Paginated envelope.

    Returning a bare list would leave no room to add the total or a cursor later
    without breaking every client, so the envelope exists from the start.
    """

    items: list[ItemRead]
    total: int
    limit: int
    offset: int

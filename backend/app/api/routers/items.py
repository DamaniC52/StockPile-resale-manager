"""Inventory item CRUD."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, OwnedItem
from app.models.enums import ItemCondition
from app.models.item import Item
from app.schemas.item import ItemCreate, ItemListResponse, ItemRead, ItemUpdate
from app.services import inventory

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, db: DbSession, user: CurrentUser) -> Item:
    try:
        return inventory.create_lot(db, user_id=user.id, payload=payload)
    except inventory.InvalidProduct:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown product_id"
        ) from None


@router.get("", response_model=ItemListResponse)
def list_items(
    db: DbSession,
    user: CurrentUser,
    # le=100 caps the page size: without it a client can request every row and
    # turn one request into an out-of-memory event.
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    in_stock: bool | None = None,
    condition: ItemCondition | None = None,
    brand_or_name: str | None = None,
) -> ItemListResponse:
    # Tenancy first, and applied to both queries below so neither can leak.
    filters = [Item.user_id == user.id]
    if in_stock is True:
        filters.append(Item.quantity_remaining > 0)
    elif in_stock is False:
        filters.append(Item.quantity_remaining == 0)
    if condition is not None:
        filters.append(Item.condition == condition.value)
    if brand_or_name:
        # Placeholder until Phase 5 replaces this with full-text search. ILIKE
        # with a leading wildcard cannot use a B-tree index.
        filters.append(Item.name.ilike(f"%{brand_or_name}%"))

    total = db.scalar(select(func.count()).select_from(Item).where(*filters)) or 0

    items = db.scalars(
        select(Item)
        .where(*filters)
        # Tiebreak on id: without a unique final sort key, rows sharing a
        # purchased_at can appear on two pages or none as you paginate.
        .order_by(Item.purchased_at.desc(), Item.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return ItemListResponse(
        items=[ItemRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item: OwnedItem) -> Item:
    # No ownership check in the body: the dependency already filtered on user_id
    # and raised 404 otherwise.
    return item


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(payload: ItemUpdate, item: OwnedItem, db: DbSession) -> Item:
    try:
        return inventory.update_lot(db, item=item, payload=payload)
    except inventory.InvalidProduct:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown product_id"
        ) from None


@router.patch("/{item_id}/quantity", response_model=ItemRead)
def adjust_item_quantity(
    new_quantity: Annotated[int, Query(gt=0)],
    item: OwnedItem,
    db: DbSession,
) -> Item:
    try:
        return inventory.adjust_quantity(db, item=item, new_quantity=new_quantity)
    except inventory.QuantityBelowSold as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot reduce below {exc.sold} units already sold",
        ) from None


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item: OwnedItem, db: DbSession) -> None:
    # Sales cascade with the item, so deleting a lot erases its profit history.
    # Acceptable for now; a voided_at soft delete is the accounting-correct fix.
    db.delete(item)
    db.commit()

"""Sale recording and listing."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models.sale import Sale
from app.schemas.sale import SaleCreate, SaleListResponse, SaleRead
from app.services import sales as sales_service

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("", response_model=SaleRead, status_code=status.HTTP_201_CREATED)
def create_sale(payload: SaleCreate, db: DbSession, user: CurrentUser) -> Sale:
    try:
        return sales_service.record_sale(db, user_id=user.id, payload=payload)
    except sales_service.ItemNotFound:
        # Same 404 for "no such item" and "not yours", so ids can't be probed.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        ) from None
    except sales_service.InsufficientQuantity as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only {exc.available} unit{'s' if exc.available != 1 else ''} "
                f"available, requested {exc.requested}"
            ),
        ) from None
    except sales_service.ListingNotForItem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Listing does not belong to that item",
        ) from None


@router.get("", response_model=SaleListResponse)
def list_sales(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    item_id: int | None = None,
    marketplace_id: int | None = None,
) -> SaleListResponse:
    filters = [Sale.user_id == user.id]
    if item_id is not None:
        filters.append(Sale.item_id == item_id)
    if marketplace_id is not None:
        filters.append(Sale.marketplace_id == marketplace_id)

    total = db.scalar(select(func.count()).select_from(Sale).where(*filters)) or 0
    rows = db.scalars(
        select(Sale)
        .where(*filters)
        # Two extra queries total (one per relationship, using IN), instead of
        # one per row. This is the N+1 fix.
        .options(selectinload(Sale.item), selectinload(Sale.marketplace))
        # Unique tiebreak so pagination is stable when sold_at repeats.
        .order_by(Sale.sold_at.desc(), Sale.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return SaleListResponse(
        sales=[SaleRead.model_validate(s) for s in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{sale_id}", status_code=status.HTTP_204_NO_CONTENT)
def void_sale(sale_id: int, db: DbSession, user: CurrentUser) -> None:
    """Reverse a sale and return its units to the lot."""
    # Ownership filtered in the query, not checked after.
    sale = db.scalar(select(Sale).where(Sale.id == sale_id, Sale.user_id == user.id))
    if sale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    sales_service.void_sale(db, sale=sale)

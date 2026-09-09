"""CSV export.

Streamed rather than assembled in memory: an export is the one endpoint whose
response grows with the size of the account, and building the whole file before
sending a byte is how it eventually runs a server out of memory.
"""

import csv
import io
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentUser, DbSession
from app.models.enums import ItemCondition
from app.models.item import Item
from app.models.sale import Sale

router = APIRouter(prefix="/export", tags=["export"])

BATCH = 500

ITEM_COLUMNS = [
    "id", "name", "size", "condition", "source", "purchased_at",
    "quantity", "quantity_remaining", "unit_cost", "acquisition_fee_total",
    "purchase_total", "capital_tied_up", "stock_status",
]

SALE_COLUMNS = [
    "id", "sold_at", "item_id", "item_name", "item_size", "marketplace",
    "quantity_sold", "unit_price", "revenue", "platform_fee", "shipping_cost",
    "other_fees", "cogs", "net_profit",
]


def _writer() -> tuple[io.StringIO, csv.writer]:
    buf = io.StringIO()
    return buf, csv.writer(buf, lineterminator="\n")


def _flush(buf: io.StringIO) -> str:
    """Take what has been written and reset the buffer.

    The rows are handed to the client as they are produced, so the buffer holds
    one batch rather than the whole file.
    """
    chunk = buf.getvalue()
    buf.seek(0)
    buf.truncate(0)
    return chunk


def _filename(kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"stockpile-{kind}-{stamp}.csv"


def _attachment(rows: Iterator[str], kind: str) -> StreamingResponse:
    return StreamingResponse(
        rows,
        media_type="text/csv; charset=utf-8",
        # Content-Disposition is what makes the browser save the file instead
        # of rendering it. Without it the CSV appears as text in the tab.
        headers={"Content-Disposition": f'attachment; filename="{_filename(kind)}"'},
    )


def _stream_items(db: Session, user_id: int, filters: list) -> Iterator[str]:
    buf, w = _writer()
    w.writerow(ITEM_COLUMNS)
    yield _flush(buf)

    stmt = (
        select(Item)
        .where(Item.user_id == user_id, *filters)
        .order_by(Item.purchased_at.desc(), Item.id.desc())
        .execution_options(yield_per=BATCH)
    )
    for item in db.scalars(stmt):
        purchase_total = item.unit_cost * item.quantity + item.acquisition_fee_total
        w.writerow([
            item.id, item.name, item.size or "", item.condition, item.source or "",
            item.purchased_at.isoformat(), item.quantity, item.quantity_remaining,
            item.unit_cost, item.acquisition_fee_total, purchase_total,
            item.unit_cost * item.quantity_remaining, item.stock_status,
        ])
        yield _flush(buf)


def _stream_sales(db: Session, user_id: int) -> Iterator[str]:
    buf, w = _writer()
    w.writerow(SALE_COLUMNS)
    yield _flush(buf)

    stmt = (
        select(Sale)
        .where(Sale.user_id == user_id)
        .options(selectinload(Sale.item), selectinload(Sale.marketplace))
        .order_by(Sale.sold_at.desc(), Sale.id.desc())
        .execution_options(yield_per=BATCH)
    )
    for sale in db.scalars(stmt):
        w.writerow([
            sale.id, sale.sold_at.isoformat(), sale.item_id, sale.item.name,
            sale.item.size or "", sale.marketplace.name, sale.quantity_sold,
            sale.unit_price, sale.revenue, sale.platform_fee, sale.shipping_cost,
            sale.other_fees, sale.cogs, sale.net_profit,
        ])
        yield _flush(buf)


@router.get("/items.csv")
def export_items(
    db: DbSession,
    user: CurrentUser,
    in_stock: bool | None = None,
    condition: ItemCondition | None = None,
) -> StreamingResponse:
    """Inventory as CSV, honouring the same filters as the list endpoint.

    Search is deliberately not a filter here: an export is a record of what you
    hold, and silently exporting only what matched a search term is a good way
    to produce an incomplete spreadsheet someone then relies on.
    """
    filters = []
    if in_stock is True:
        filters.append(Item.quantity_remaining > 0)
    elif in_stock is False:
        filters.append(Item.quantity_remaining == 0)
    if condition is not None:
        filters.append(Item.condition == condition.value)

    return _attachment(_stream_items(db, user.id, filters), "inventory")


@router.get("/sales.csv")
def export_sales(db: DbSession, user: CurrentUser) -> StreamingResponse:
    """Sales as CSV, including the computed revenue, COGS and net profit."""
    return _attachment(_stream_sales(db, user.id), "sales")

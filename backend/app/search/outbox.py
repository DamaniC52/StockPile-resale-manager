"""Enqueue index changes with the data change; drain them to the index later.

Only Elasticsearch needs this. The Postgres backend reads the source of truth
directly, so there is nothing to keep in sync — the outbox is the cost of a
second datastore, paid once here rather than at every call site.
"""

import logging
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.search_outbox import SearchOutbox
from app.search.elastic import ElasticIndexer, IndexOp, document_for, version_for

log = logging.getLogger(__name__)

Op = Literal["index", "delete"]


def enqueue(db: Session, *, item_id: int, user_id: int, op: Op) -> None:
    """Record an index change. Call inside the transaction that changes the item.

    Not committed here: committing is the caller's decision, and the whole
    point is that this row and the item change land together or not at all.
    """
    db.add(SearchOutbox(item_id=item_id, user_id=user_id, op=op))


def drain(db: Session, indexer: ElasticIndexer, *, batch: int = 500) -> int:
    """Apply one batch of pending rows to the index. Returns how many succeeded.

    Safe to run from several processes at once: SKIP LOCKED hands each worker
    a disjoint set of rows instead of making them queue on the same ones or
    double-apply them.
    """
    rows = (
        db.execute(
            select(SearchOutbox)
            .where(SearchOutbox.processed_at.is_(None))
            .order_by(SearchOutbox.created_at, SearchOutbox.id)
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    # Several rows for one item collapse to its latest state. Ordered ascending,
    # so the last assignment wins.
    latest: dict[int, SearchOutbox] = {}
    for r in rows:
        latest[r.item_id] = r

    # Documents come from Postgres now, not from the row: the row says "this
    # item changed", the database says what it currently is.
    items = {
        i.id: i for i in db.scalars(select(Item).where(Item.id.in_(list(latest))))
    }

    ops: list[IndexOp] = []
    for item_id, row in latest.items():
        item = items.get(item_id)
        if row.op == "index" and item is not None:
            ops.append(IndexOp("index", item_id, version_for(item), document_for(item)))
        else:
            # Either an explicit delete, or an index request for an item that
            # was deleted before the drainer got to it. Same outcome.
            ops.append(IndexOp("delete", item_id, int(row.created_at.timestamp() * 1000)))

    try:
        result = indexer.apply(ops)
    except Exception:
        # Release the row locks; the rows stay pending and are retried.
        db.rollback()
        raise

    now = func.now()
    for r in rows:
        if r.item_id in result.ok:
            r.processed_at = now
        else:
            r.attempts += 1
            r.last_error = result.failed.get(r.item_id, "unknown")
    db.commit()

    if result.failed:
        log.warning("search sync: %d item(s) failed and will retry", len(result.failed))
    return len(result.ok)


def pending_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(SearchOutbox).where(SearchOutbox.processed_at.is_(None))
    ) or 0

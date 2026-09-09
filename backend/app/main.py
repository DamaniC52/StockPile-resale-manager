"""FastAPI application entry point."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routers import auth, dashboard, items, marketplaces, sales
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db
from app.search import ElasticIndexer, get_indexer
from app.search.outbox import drain

log = logging.getLogger(__name__)
settings = get_settings()


def _drain_backlog(indexer: ElasticIndexer) -> None:
    with SessionLocal() as db:
        while drain(db, indexer):
            pass


async def _sync_loop(indexer: ElasticIndexer, interval: float) -> None:
    """Push outbox rows to the index every `interval` seconds.

    Runs in the API process for simplicity. The outbox makes this safe to move
    to a separate worker — or several — without changing anything else.
    """
    while True:
        try:
            await asyncio.to_thread(_drain_backlog, indexer)
        except Exception:
            log.exception("search sync failed; rows stay pending and will retry")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task: asyncio.Task | None = None
    indexer = get_indexer()
    if indexer is not None:
        try:
            await asyncio.to_thread(indexer.ensure_index)
        except Exception:
            # Not fatal: search falls back to Postgres until the cluster is up,
            # and the sync loop keeps retrying the backlog.
            log.exception("elasticsearch unreachable at startup")
        task = asyncio.create_task(_sync_loop(indexer, settings.SEARCH_SYNC_INTERVAL))
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="StockPile API",
    description="Resale inventory and profit/loss tracking.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every route lives under /api so the Vite dev proxy and Vercel rewrites have a
# single prefix to forward.
app.include_router(auth.router, prefix="/api")
app.include_router(items.router, prefix="/api")
app.include_router(sales.router, prefix="/api")
app.include_router(marketplaces.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness check. Queries the database so a green response means something."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return {"status": "degraded", "db": "unreachable"}
    return {"status": "ok", "db": "connected"}

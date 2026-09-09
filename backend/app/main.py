"""FastAPI application entry point."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routers import auth, dashboard, items, marketplaces, sales
from app.core.config import get_settings
from app.db.session import get_db

settings = get_settings()

app = FastAPI(
    title="StockPile API",
    description="Resale inventory and profit/loss tracking.",
    version="0.1.0",
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

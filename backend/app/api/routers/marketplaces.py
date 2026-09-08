"""Marketplace reference data."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.marketplace import Marketplace

router = APIRouter(prefix="/marketplaces", tags=["marketplaces"])


class MarketplaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    default_fee_pct: float | None


@router.get("", response_model=list[MarketplaceRead])
def list_marketplaces(db: DbSession, user: CurrentUser) -> list[Marketplace]:
    """Global reference data, but still behind auth: an unauthenticated client
    has no reason to enumerate it."""
    return list(
        db.scalars(
            select(Marketplace).where(Marketplace.is_active).order_by(Marketplace.name)
        ).all()
    )

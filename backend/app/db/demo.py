"""Seed a demo account so the deployed app is explorable without signing up.

    python -m app.db.demo

Resets the demo user's data every run, so redeploying restores it after
visitors have edited it. Only ever touches that one account.
"""

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.item import Item
from app.models.marketplace import Marketplace
from app.models.sale import Sale
from app.models.search_outbox import SearchOutbox
from app.models.user import User
from app.schemas.sale import SaleCreate
from app.services import sales as sales_service

DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@stockpile.app")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo-password-123")

# (name, size, condition, qty, unit_cost, acquisition_fee, source, bought_days_ago)
LOTS = [
    ("Jordan 4 Retro Bred", "10.5", "new", 3, "180.00", "20.00", "SNKRS", 89),
    ("Supreme Box Logo Hoodie FW23", "M", "new", 1, "220.00", "0.00", "Supreme", 84),
    ("New Balance 990v6 Grey", "9", "new", 2, "150.00", "12.00", "Retail", 80),
    ("Travis Scott Jordan 1 Low", "11", "like_new", 1, "900.00", "0.00", "GOAT", 76),
    ("Nike Dunk Low Panda", "8.5", "new", 4, "95.00", "18.00", "Retail", 70),
    ("Stussy 8 Ball Tee", "L", "used", 2, "40.00", "0.00", "Depop", 64),
    ("Yeezy Slide Bone", "10", "new", 2, "85.00", "9.00", "Adidas", 58),
    ("Corteiz Cargos", "32", "new", 1, "130.00", "0.00", "Corteiz", 50),
]

# (lot index, qty, unit_price, platform_fee, shipping, sold_days_ago)
# One deliberate loss: the Stussy tee, so the profit curve is not a clean climb.
SALES = [
    (0, 1, "295.00", "38.35", "15.00", 73),
    (4, 2, "128.00", "16.64", "10.00", 68),
    (2, 1, "195.00", "25.35", "12.00", 52),
    (5, 1, "32.00", "4.16", "6.00", 45),
    (6, 1, "72.00", "9.36", "8.00", 35),
    (0, 2, "318.00", "41.34", "15.00", 26),
    (4, 1, "135.00", "17.55", "10.00", 10),
    (3, 1, "1180.00", "153.40", "22.00", 7),
]


def seed_demo() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD))
            db.add(user)
            db.flush()
        else:
            # Reset rather than accumulate: visitors can edit this account, and
            # a redeploy should hand the next visitor a clean example.
            db.execute(delete(Sale).where(Sale.user_id == user.id))
            item_ids = db.scalars(select(Item.id).where(Item.user_id == user.id)).all()
            if item_ids:
                db.execute(delete(SearchOutbox).where(SearchOutbox.item_id.in_(item_ids)))
                db.execute(delete(Item).where(Item.user_id == user.id))
            user.hashed_password = hash_password(DEMO_PASSWORD)
        db.commit()

        marketplaces = {m.slug: m.id for m in db.scalars(select(Marketplace))}
        if not marketplaces:
            raise RuntimeError("run `python -m app.db.seed` first: no marketplaces")
        # Spread sales across platforms so the by-marketplace chart has shape.
        platforms = [
            marketplaces.get(s, next(iter(marketplaces.values())))
            for s in ("stockx", "ebay", "goat", "depop", "grailed")
        ]

        today = date.today()
        items: list[Item] = []
        for name, size, condition, qty, cost, fee, source, days in LOTS:
            item = Item(
                user_id=user.id, name=name, size=size, condition=condition,
                quantity=qty, quantity_remaining=qty,
                unit_cost=Decimal(cost), acquisition_fee_total=Decimal(fee),
                purchased_at=today - timedelta(days=days), source=source,
            )
            db.add(item)
            items.append(item)
        db.commit()

        now = datetime.now(timezone.utc)
        for n, (idx, qty, price, platform_fee, shipping, days) in enumerate(SALES):
            sales_service.record_sale(
                db, user_id=user.id,
                payload=SaleCreate(
                    item_id=items[idx].id,
                    marketplace_id=platforms[n % len(platforms)],
                    quantity_sold=qty,
                    unit_price=Decimal(price),
                    platform_fee=Decimal(platform_fee),
                    shipping_cost=Decimal(shipping),
                    sold_at=now - timedelta(days=days),
                ),
            )

        total = sum(
            s.net_profit for s in db.scalars(select(Sale).where(Sale.user_id == user.id))
        )
        print(f"demo account {DEMO_EMAIL}: {len(items)} lots, {len(SALES)} sales, net {total}")


if __name__ == "__main__":
    seed_demo()

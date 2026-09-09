"""CSV export: correct content, correct scope, correct headers."""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app
from app.models.item import Item
from app.models.marketplace import Marketplace
from app.models.user import User
from app.schemas.sale import SaleCreate
from app.services import sales as sales_service


@pytest.fixture
def client(db):
    """A TestClient whose requests use the test session."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def account(db, client):
    """A user with two lots and one sale, plus a second user's lot."""
    client.post("/api/auth/signup", json={"email": "e@test.com", "password": "password-123"})
    token = client.post(
        "/api/auth/login", json={"email": "e@test.com", "password": "password-123"}
    ).json()["access_token"]

    owner = db.query(User).filter(User.email == "e@test.com").one()
    other = User(email="other@test.com", hashed_password="x")
    marketplace = Marketplace(name="StockX", slug="stockx")
    db.add_all([other, marketplace])
    db.flush()

    sold_out = Item(
        user_id=owner.id, name="Jordan 4 Bred", size="10.5", source="SNKRS",
        quantity=2, quantity_remaining=2, unit_cost=Decimal("180.00"),
        acquisition_fee_total=Decimal("20.00"), purchased_at=date(2026, 1, 1),
    )
    in_stock = Item(
        user_id=owner.id, name="Yeezy Slide", size="10",
        quantity=1, quantity_remaining=1, unit_cost=Decimal("85.00"),
        purchased_at=date(2026, 2, 1),
    )
    db.add_all([sold_out, in_stock])
    # Must not appear in either export.
    db.add(Item(
        user_id=other.id, name="Someone Elses Lot", quantity=1, quantity_remaining=1,
        unit_cost=Decimal("50.00"), purchased_at=date(2026, 1, 1),
    ))
    db.commit()

    sales_service.record_sale(
        db, user_id=owner.id,
        payload=SaleCreate(
            item_id=sold_out.id, marketplace_id=marketplace.id, quantity_sold=2,
            unit_price=Decimal("310.00"), platform_fee=Decimal("40.30"),
            shipping_cost=Decimal("15.00"),
            sold_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ),
    )
    return {"Authorization": f"Bearer {token}"}, owner


def rows(response) -> list[dict]:
    return list(csv.DictReader(io.StringIO(response.text)))


def test_items_export_returns_a_csv_attachment(client, account):
    headers, _ = account
    r = client.get("/api/export/items.csv", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    # Without this header the browser renders the CSV instead of saving it.
    assert r.headers["content-disposition"].startswith("attachment; filename=")
    assert ".csv" in r.headers["content-disposition"]


def test_items_export_content(client, account):
    headers, _ = account
    data = rows(client.get("/api/export/items.csv", headers=headers))
    assert len(data) == 2

    jordan = next(r for r in data if r["name"] == "Jordan 4 Bred")
    assert jordan["size"] == "10.5"
    assert jordan["quantity"] == "2"
    assert jordan["quantity_remaining"] == "0"
    assert jordan["stock_status"] == "sold_out"
    # 2 x 180.00 + 20.00 acquisition fee
    assert jordan["purchase_total"] == "380.00"
    assert jordan["capital_tied_up"] == "0.00"


def test_items_export_is_scoped_to_the_caller(client, account):
    headers, _ = account
    names = {r["name"] for r in rows(client.get("/api/export/items.csv", headers=headers))}
    assert "Someone Elses Lot" not in names


def test_items_export_honours_the_in_stock_filter(client, account):
    headers, _ = account
    data = rows(client.get("/api/export/items.csv", headers=headers, params={"in_stock": "true"}))
    assert [r["name"] for r in data] == ["Yeezy Slide"]


def test_sales_export_includes_computed_profit(client, account):
    headers, _ = account
    data = rows(client.get("/api/export/sales.csv", headers=headers))
    assert len(data) == 1
    sale = data[0]
    assert sale["item_name"] == "Jordan 4 Bred"
    assert sale["marketplace"] == "StockX"
    assert sale["quantity_sold"] == "2"
    assert sale["revenue"] == "620.00"
    # 2 x 180.00 unit cost + 20.00 allocated acquisition fee
    assert sale["cogs"] == "380.00"
    # 620.00 - 40.30 - 15.00 - 380.00
    assert sale["net_profit"] == "184.70"


def test_export_requires_authentication(client):
    assert client.get("/api/export/items.csv").status_code == 401
    assert client.get("/api/export/sales.csv").status_code == 401

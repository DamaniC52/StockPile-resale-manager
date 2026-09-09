"""The application module itself must import and expose its routes.

Nothing else in the suite imports app.main, so without this a syntax or import
error in the entry point passes every test and fails only at deploy time.
"""

from fastapi.testclient import TestClient

from app.main import app

EXPECTED = {
    "/api/auth/login", "/api/auth/signup", "/api/auth/me",
    "/api/items", "/api/items/{item_id}", "/api/items/{item_id}/quantity",
    "/api/sales", "/api/sales/{sale_id}",
    "/api/marketplaces",
    "/api/export/items.csv", "/api/export/sales.csv",
    "/api/dashboard/summary", "/api/dashboard/profit-over-time",
    "/api/dashboard/by-marketplace", "/api/dashboard/inventory-aging",
    "/api/dashboard/top-items",
    "/health",
}


def test_all_routes_are_registered():
    assert set(app.openapi()["paths"]) == EXPECTED


def test_unauthenticated_requests_are_rejected():
    # TestClient runs the lifespan; with the default Postgres backend that
    # starts no background task, so this is cheap.
    with TestClient(app) as client:
        for path in ("/api/items", "/api/sales", "/api/dashboard/summary"):
            assert client.get(path).status_code == 401, path

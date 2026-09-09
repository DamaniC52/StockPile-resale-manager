"""Rate limiting on the auth endpoints."""

import time

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core import ratelimit
from app.core.config import Settings
from app.core.ratelimit import SlidingWindowLimiter
from app.main import app


@pytest.fixture
def client(db, monkeypatch):
    # A tiny limit so the test does not have to make ten requests.
    monkeypatch.setattr(ratelimit, "_auth_limiter", SlidingWindowLimiter(3, 60))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client, password="wrong-password"):
    return client.post(
        "/api/auth/login", json={"email": "nobody@test.com", "password": password}
    )


def test_repeated_attempts_are_eventually_rejected(client):
    for _ in range(3):
        assert login(client).status_code == 401

    blocked = login(client)
    assert blocked.status_code == 429
    # RFC 6585: a 429 tells the client how long to wait.
    assert int(blocked.headers["retry-after"]) > 0


def test_the_window_expires(client, monkeypatch):
    for _ in range(3):
        login(client)
    assert login(client).status_code == 429

    # Advance past the window rather than sleeping through it.
    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + 61)
    assert login(client).status_code == 401


def test_clients_are_limited_independently(client):
    for _ in range(3):
        client.post(
            "/api/auth/login",
            json={"email": "a@test.com", "password": "x"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
    # The first client is now over its limit.
    assert client.post(
        "/api/auth/login",
        json={"email": "a@test.com", "password": "x"},
        headers={"X-Forwarded-For": "10.0.0.1"},
    ).status_code == 429
    # A different address is unaffected.
    assert client.post(
        "/api/auth/login",
        json={"email": "a@test.com", "password": "x"},
        headers={"X-Forwarded-For": "10.0.0.2"},
    ).status_code == 401


def test_signup_is_limited_too(client):
    codes = [
        client.post(
            "/api/auth/signup",
            json={"email": f"u{n}@test.com", "password": "password-123"},
        ).status_code
        for n in range(4)
    ]
    assert codes[:3] == [201, 201, 201]
    assert codes[3] == 429


def test_authenticated_endpoints_are_not_limited(client):
    """Only auth is limited; a signed-in user browsing must not hit a 429."""
    client.post("/api/auth/signup", json={"email": "u@test.com", "password": "password-123"})
    token = client.post(
        "/api/auth/login", json={"email": "u@test.com", "password": "password-123"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(10):
        assert client.get("/api/items", headers=headers).status_code == 200


# ---- the database URL rewrite that managed providers require ---------------


@pytest.mark.parametrize(
    "given",
    ["postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"],
)
def test_database_url_is_normalized_to_psycopg(given):
    """Render injects postgres://, which SQLAlchemy rejects, and postgresql://,
    which resolves to psycopg2 — not installed."""
    settings = Settings(DATABASE_URL=given, JWT_SECRET="x")
    assert settings.DATABASE_URL == "postgresql+psycopg://u:p@h:5432/db"

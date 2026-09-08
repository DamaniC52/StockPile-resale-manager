# StockPile

Inventory and profit/loss tracking for resellers — sneakers, streetwear and collectibles bought and sold across eBay, StockX, Depop and Grailed.

Resellers mostly run on spreadsheets, which handle *what you own* but fall apart on *what you actually made*: fees differ per platform, shipping comes out of your pocket, and a lot bought as five pairs sells in three separate transactions months apart. StockPile tracks purchases as lots, records partial sales against them, and computes net profit per sale after every fee.

**Stack:** FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 · Alembic · React 19 · Vite · Tailwind 4 · Recharts

![Portfolio view: realized profit of $352.85 charted as a step function over three months](docs/screenshots/portfolio.png)

Profit is charted as a step function because it changes only when a sale is recorded, not continuously. The drop in late July is a real loss — a tee that sold for less than it cost.

![Inventory table listing lots with size, source, status, units remaining, unit cost and capital tied up](docs/screenshots/inventory.png)

Each row is a lot rather than a single unit, so `1/4` means one of four units is still unsold.

![Add inventory dialog with fields for item, size, condition, units, cost per unit and purchase fees](docs/screenshots/add-item.png)

Purchase fees are recorded against the whole lot, not per unit, and are divided across sales as they happen.

---

## Running it

Requires Docker and [uv](https://github.com/astral-sh/uv). Node 20+ for the frontend.

```bash
# 1. Database
docker compose up -d db

# 2. Backend
cd backend
uv venv && uv pip install -r requirements.txt
# create .env with the variables listed below
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m app.db.seed
.venv/Scripts/python -m uvicorn app.main:app --reload

# 3. Frontend
cd ../frontend
npm install
npm run dev
```

The app runs at `localhost:5173`; the API at `localhost:8000` with interactive docs at `/docs`. Vite proxies `/api` to the backend, so CORS doesn't apply in development.

### Environment variables

`backend/.env`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://stockpile:dev@localhost:5432/stockpile` — the `+psycopg` suffix selects psycopg 3 |
| `JWT_SECRET` | Signs access tokens. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `JWT_ALGORITHM` | Defaults to `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Defaults to `60` |
| `CORS_ORIGINS` | Comma-separated. Only used when frontend and API are on different domains |

### Tests

```bash
cd backend && .venv/Scripts/python -m pytest
```

Tests run against a real Postgres instance in a separate `stockpile_test` database, not SQLite and not mocks — the behaviours that matter most here are database behaviours.

---

## The interesting parts

Full reasoning, including the options rejected and what each choice costs, is in [`docs/DESIGN.md`](docs/DESIGN.md).

### Inventory is modelled as lots, and overselling is prevented in one statement

An `items` row is *N identical units* bought together, and sales draw partial quantities from it. That makes concurrent sales of the last unit a real problem: two requests reading "1 remaining" and both writing "0" is a lost update, and it sells inventory that doesn't exist.

The write path is a single conditional `UPDATE`:

```sql
UPDATE items SET quantity_remaining = quantity_remaining - :n
WHERE id = :id AND user_id = :user AND quantity_remaining >= :n
RETURNING quantity, quantity_remaining, unit_cost, acquisition_fee_total
```

Zero rows updated *is* the rejection signal. Under Postgres's READ COMMITTED isolation, an `UPDATE` that meets a concurrently-modified row waits for that transaction and then re-evaluates its `WHERE` clause against the new row version, so the stock check cannot go stale.

`tests/test_concurrency.py` runs eight threads against a lot of three and asserts exactly three succeed. Swapping in the naive read-then-write implementation makes it fail — eight units sold from a lot of three, **with zero constraint violations**, because every individual write was a legal value based on a stale read. A `CHECK` constraint prevents impossible values; it does not prevent lost updates. Both are needed and they defend different things.

### `quantity_remaining` is denormalized so a constraint becomes possible

It could be derived from `quantity - SUM(sales.quantity_sold)`. That version can never drift, but it also can't be constrained — a `CHECK` cannot reference another table, so overselling would be preventable only in application code. Storing the counter makes `quantity_remaining >= 0` row-local, and therefore enforceable by Postgres. Denormalization here buys a correctness guarantee, not speed.

### Cross-tenant access is unrepresentable, not merely checked

`user_id` is denormalized onto `listings` and `sales` so tenant filtering is a single-table index scan. The consistency risk that creates is closed by a composite foreign key:

```sql
FOREIGN KEY (item_id, user_id) REFERENCES items(id, user_id)
```

A sale claiming user 4 while referencing an item owned by user 7 is rejected by the database. IDOR — OWASP API1, Broken Object Level Authorization — becomes a constraint violation rather than a class of application bug. The API layer adds defense in depth: ownership-scoped routes resolve objects through one dependency that filters on `user_id` and returns **404, not 403**, since 403 would confirm the row exists and let an attacker enumerate valid ids.

### Cost basis is snapshotted onto each sale

`sales` stores its own `unit_cost_snapshot`, so correcting an item's cost in June cannot rewrite March's reported profit — the same reason an invoice line copies unit price rather than joining to a product table. It also makes every profit aggregation a single-table `SUM` with no joins.

### Profit is defined once and computed in either language

`revenue`, `cogs` and `net_profit` are SQLAlchemy hybrid properties with both a Python body and a SQL expression. `sale.net_profit` runs in Python; `func.sum(Sale.net_profit)` compiles to SQL and aggregates in the database instead of loading every row into memory.

### Flat purchase fees are allocated so the parts sum exactly

A $20 inbound shipping charge across a lot of three is $6.6667 per unit — rounded, three shares total $20.01. The final sale of a lot absorbs the remainder instead, making the total exact by construction. Verified in `tests/test_sales.py`, including under concurrency.

---

## Layout

```
backend/
  app/
    models/       SQLAlchemy models, constraints and indexes
    schemas/      Pydantic request/response contracts
    services/     Multi-step writes that own an invariant
    api/          Routers and shared dependencies
    db/           Engine, session, declarative base, seed data
  alembic/        Migrations
  tests/          Real-Postgres tests, including concurrency
frontend/
  src/
    pages/        Portfolio, Inventory, sign-in
    components/   Forms, modal, shared UI
    lib/          API client, auth and theme context
docs/DESIGN.md    Data model and architecture decisions
```

There is no repository layer, deliberately. SQLAlchemy's `Session` already implements Unit of Work and Identity Map, and the schema is intentionally Postgres-shaped, so there is no second backend to abstract over. `services/` exists for a narrower reason: `record_sale` owns an invariant that must live in exactly one place once both a REST endpoint and an importer call it.

## Status

Working: authentication, item CRUD with filtering and pagination, sales with profit calculation, portfolio view with a profit chart, light and dark themes.

Not built yet: Postgres full-text search (item search currently uses `ILIKE`, which cannot use an index), an Elasticsearch backend behind the same `SearchService` interface, server-side dashboard aggregations, and a scheduled market-price poller.

Deliberately out of scope, since this is not deployed publicly: email verification, password reset, refresh tokens, and rate limiting on the login endpoint. All four would be required before exposing it to real users.

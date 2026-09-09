# StockPile

Inventory and profit tracking for resellers — sneakers, streetwear and collectibles sold across eBay, StockX, Depop and Grailed.

Most resellers track this in a spreadsheet, which handles *what you own* but falls apart on *what you actually made*. Fees differ per platform, shipping comes out of your pocket, and five pairs bought together often sell in three transactions months apart. StockPile records purchases as lots, logs partial sales against them, and computes net profit after every fee.

**Stack:** FastAPI · PostgreSQL · SQLAlchemy · Alembic · Elasticsearch · React · Vite · Tailwind

**Live demo:** https://stockpile-three.vercel.app — sign in as `demo@stockpile.app` / `demo-password-123`. The API sleeps when idle, so the first load can take 30 seconds.

![Portfolio view showing realized profit charted over three months](docs/screenshots/portfolio.png)

![Inventory table listing lots with size, status, units remaining and capital tied up](docs/screenshots/inventory.png)

Each row is a lot, not a single item, so `1/4` means one of four units is still unsold.

![Add inventory dialog](docs/screenshots/add-item.png)

## Running it

Needs Docker, [uv](https://github.com/astral-sh/uv), and Node 20+.

```bash
docker compose up -d db

cd backend
uv venv && uv pip install -r requirements.txt
# create .env with DATABASE_URL and JWT_SECRET (see below)
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m app.db.seed
.venv/Scripts/python -m uvicorn app.main:app --reload

cd ../frontend
npm install && npm run dev
```

App at `localhost:5173`, API docs at `localhost:8000/docs`.

`backend/.env`:

```
DATABASE_URL=postgresql+psycopg://stockpile:dev@localhost:5432/stockpile
JWT_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(32))">
SEARCH_BACKEND=postgres          # or elasticsearch
```

Tests run against real Postgres, not SQLite or mocks, since most of what matters here is database behaviour:

```bash
cd backend && .venv/Scripts/python -m pytest
```

81 tests. The Elasticsearch ones skip if the container isn't running.

## Notes on a few decisions

Full reasoning is in [`docs/DESIGN.md`](docs/DESIGN.md).

### Overselling

An item row is a lot of N units, so two people buying the last one at the same time is a real problem. Read the count, check it, write it back, and two requests both see "1 remaining" and both write "0".

The write is one statement instead:

```sql
UPDATE items SET quantity_remaining = quantity_remaining - :n
WHERE id = :id AND user_id = :user AND quantity_remaining >= :n
```

Zero rows updated means rejected. Under Postgres's default isolation, an UPDATE that hits a row another transaction just changed waits for it and re-checks the WHERE clause, so the stock test can't go stale.

`tests/test_concurrency.py` runs 8 threads against a lot of 3 and asserts exactly 3 succeed. The naive version fails it by selling 8 units — with no constraint violations, because every individual write was a legal value based on a stale read. A CHECK constraint stops impossible values; it doesn't stop lost updates.

### Dashboard queries

Profit used to be summed in the browser, which capped out at 100 records and shipped every sale over the wire. It's one grouped SQL query now.

On a 300,000-row benchmark with `EXPLAIN (ANALYZE, BUFFERS)`:

| | With index | Without |
|---|---|---|
| Buffers | 430 | 4,017 |
| CPU workers | 1 | 3 |
| Rows discarded | 0 | ~274,000 |
| Time | 37 ms | 45 ms |

The wall clock barely moved, which is the interesting part — Postgres kept the sequential scan competitive by throwing two extra cores at it. Buffers are the honest number on an idle machine.

### Search

Search sits behind an interface with two implementations: Postgres full-text and Elasticsearch. The same test suite runs against both and asserts identical results.

Postgres uses a generated `tsvector` column with a GIN index, plus `pg_trgm` for typos, so "hoodies" finds "Hoodie" and "jordn" finds "Jordan". On 120,000 rows a selective query went from 2.7 ms to 0.17 ms.

It's slower than `ILIKE` on broad queries, though — ranking 10,000 matches costs more than not ranking them. Worth saying, since the win is stemming and relevance, not raw speed everywhere.

Production runs the Postgres backend because a single Elasticsearch node wants about a gigabyte of heap and doesn't fit a free instance. That's a config change rather than a code change, which is the actual argument for having built the interface.

Keeping Elasticsearch in sync uses a transactional outbox: every item change writes a row in the same transaction as the change itself, and a background loop applies them. Dual-writing would let the two stores drift silently when the second write fails.

### Tenant isolation

`user_id` is denormalized onto sales and listings so filtering is a single-table index scan. A composite foreign key stops that from drifting:

```sql
FOREIGN KEY (item_id, user_id) REFERENCES items(id, user_id)
```

A sale claiming user 4 while pointing at user 7's item gets rejected by the database. Routes also return 404 rather than 403 for someone else's row, so IDs can't be probed.

## Deploying

Postgres on Neon, API on Render (`render.yaml`), frontend on Vercel (`frontend/vercel.json`).

Neon rather than Render's own Postgres because Render deletes a free database 30 days after creation, which would quietly break the demo link. Neon's free tier doesn't expire.

Vercel rewrites `/api` to the Render service, so the browser only talks to one origin and CORS never applies.

Rate limiting on the auth routes and a constant-time login path were added once this became internet-facing. The login one matters: identical error messages don't help if an unknown email skips bcrypt and answers in 1 ms while a real one takes 250 ms.

## Layout

```
backend/app/
  models/     SQLAlchemy models, constraints, indexes
  schemas/    Pydantic request/response types
  services/   Writes that own an invariant
  queries/    Read-side aggregations
  search/     Search interface, both backends, outbox
  api/        Routers and dependencies
frontend/src/
  pages/      Portfolio, Inventory, Sales, sign-in
  components/ Forms, modal, shared UI
```

No repository layer. SQLAlchemy's `Session` is already a unit of work, and the schema is deliberately Postgres-shaped, so there's no second backend to abstract over. `services/` exists for a narrower reason: `record_sale` owns an invariant that has to live in one place.

## Status

Working: auth, item CRUD, sales and profit, SQL dashboard, search on either backend, CSV export, dark mode, mobile.

Not built: market price tracking. `products` and `price_snapshots` are modelled and indexed, but nothing creates products yet, so a price poller would have nothing to attach to.

Out of scope: email verification, password reset, refresh tokens.

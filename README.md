# StockPile

Inventory and profit/loss tracking for resellers — sneakers, streetwear and collectibles bought and sold across eBay, StockX, Depop and Grailed.

Resellers mostly run on spreadsheets, which handle *what you own* but fall apart on *what you actually made*: fees differ per platform, shipping comes out of your pocket, and a lot bought as five pairs sells in three separate transactions months apart. StockPile tracks purchases as lots, records partial sales against them, and computes net profit per sale after every fee.

**Stack:** FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 · Alembic · Elasticsearch 8 · React 19 · Vite · Tailwind 4 · Recharts

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
# 1. Database (Elasticsearch is optional; see Search below)
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
| `SEARCH_BACKEND` | `postgres` (default) or `elasticsearch` |
| `ELASTICSEARCH_URL` | Defaults to `http://localhost:9200` |
| `ELASTICSEARCH_INDEX` | Alias name, default `stockpile-items`. Reindexing swaps what it points at |
| `SEARCH_SYNC_INTERVAL` | Seconds between outbox drains, default `2` |

To search with Elasticsearch instead of Postgres:

```bash
docker compose up -d elasticsearch          # ~40s to become healthy
SEARCH_BACKEND=elasticsearch .venv/Scripts/python -m app.search.cli reindex
SEARCH_BACKEND=elasticsearch .venv/Scripts/python -m uvicorn app.main:app --reload
```

From then on the API keeps the index in sync itself. `python -m app.search.cli status` shows the alias target and any pending changes.

### Tests

```bash
cd backend && .venv/Scripts/python -m pytest
```

Tests run against a real Postgres instance in a separate `stockpile_test` database, not SQLite and not mocks — the behaviours that matter most here are database behaviours. The search tests run against both backends; the Elasticsearch cases skip, rather than fail, when the container is not running.

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

### The dashboard aggregates in Postgres, and the index earns its place

Profit over time is one grouped query rather than a fetch-and-sum in the browser:

```sql
SELECT date_trunc('month', sold_at) AS period, SUM(...) AS net_profit
FROM sales WHERE user_id = :user AND sold_at >= :since
GROUP BY period ORDER BY period
```

Benchmarked on 300,000 sales across four tenants, 60,000 of them the caller's,
with `EXPLAIN (ANALYZE, BUFFERS)`:

| | With `ix_sales_user_id_sold_at` | Index scans disabled |
|---|---|---|
| Access path | Bitmap Index Scan | Parallel Seq Scan |
| **Shared buffers** | **430** | 4,017 |
| CPU workers | 1 | 3 |
| Rows read then discarded | 0 | ~274,000 |
| Execution time | 37 ms | 45 ms |

The wall-clock difference is small, and that is the interesting part: Postgres
kept the sequential scan competitive by launching two extra parallel workers.
The index does the same work with **9x less I/O on a single core** where the
scan needs three, and reads none of the other tenants' rows. On an idle laptop
that looks like 8 ms; under concurrent load those cores are not free.

Buffers, not elapsed time, are the honest measure of a query on a machine with
spare CPU.

### Search is full-text, and the benchmark is not the one you'd expect

Item search runs through a `SearchService` protocol with a Postgres
implementation today and an Elasticsearch one behind the same interface later.
Both return ranked ids; rows still come from Postgres, so results can never go
stale relative to the database.

The searchable text is a **stored generated column**:

```sql
search_vector tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('english', coalesce(name,   '')), 'A') ||
  setweight(to_tsvector('english', coalesce(source, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(size,   '')), 'C')
) STORED
```

Postgres maintains it on every write, so it cannot drift — no trigger and no
application code. Note this is the same mechanism ruled out for
`quantity_remaining`: a generated expression must be `IMMUTABLE` and reference
only its own row. Summing child rows fails both tests; this passes both. (The
two-argument `to_tsvector` matters — the one-argument form reads a session
setting and is only `STABLE`.)

`setweight` ranks a name match above a source match, so searching "Supreme"
puts the Supreme hoodie above a lot merely *bought from* Supreme.

Full-text alone cannot match a half-typed word, so a `pg_trgm`
`word_similarity` branch runs alongside it for single bare words —
`word_similarity`, not `similarity`, because the latter compares against the
whole name: "jorda" against "Jordan 4 Retro Bred" scores 0.24 one way and 0.83
the other.

Measured on 120,000 lots with `EXPLAIN (ANALYZE, BUFFERS)`:

| Query shape | `ILIKE '%…%'` | Full-text |
|---|---|---|
| Selective (`salomon fragment 481`) | 2.7 ms, 109 buffers | **0.17 ms, 15 buffers** |
| Broad (~10,000 matches), ranked | 2.5 ms, 610 buffers | 19.4 ms, 1,258 buffers |

Full-text is 16x faster on selective queries and **slower** on broad ones, and
both numbers are worth stating. Ranking 10,000 matches by relevance costs more
than not ranking them: `ILIKE` ordered by date stops after 50 rows, while
relevance ordering has to score every match first. That is the price of ranked
results, not a defect.

The trigram index also turns out to make `ILIKE` itself indexable
(`gin_trgm_ops` supports `ILIKE '%…%'`), so the migration improved the thing it
replaced. The case for full-text here is stemming, ranking, and operator
support — "hoodies" finding "Hoodie", and `-dunk` excluding it — not raw speed
on every query shape.

One behavioural difference to know: `ILIKE` matches substrings and full-text
matches whole tokens, so `481` finds `4813` under `ILIKE` and not under
full-text.

### Elasticsearch is kept consistent through a transactional outbox

Set `SEARCH_BACKEND=elasticsearch` and search runs against an Elasticsearch index — behind the same `SearchService` interface, verified by the same parametrized test suite. Writing to two datastores is where a feature like this usually goes wrong, so the sync path is the part worth reading.

Dual writes (commit to Postgres, then index) are rejected: if the second write fails, or the process dies between them, the two silently diverge. Instead every item change writes a row to `search_outbox` **in the same transaction**, so either both land or neither does. A drainer applies pending rows: `SELECT ... FOR UPDATE SKIP LOCKED` lets several workers drain without double-applying, several changes to one item collapse to its final state, and the document is read from Postgres at drain time rather than from the row. Rows are marked processed only on success; on failure they stay pending with the error recorded, so an unreachable cluster loses nothing.

Out-of-order and duplicate applies are made harmless with external versioning: each document carries `updated_at` as its version with `version_type=external_gte`, so a stale write is refused — and the refusal is treated as success, because the index already holds the newer state.

The index is addressed through an alias. `python -m app.search.cli reindex` builds a new index from Postgres and swaps the alias in one call, so readers never see a half-built index and a bad mapping change rolls back by swapping again. Mappings are explicit with `dynamic: strict`; the analyzer mirrors Postgres's `english` configuration so both backends agree that "hoodies" is `hoodi`, and the same single-bare-word rule governs fuzzy matching on both.

If the cluster is unreachable, `ElasticSearchService` logs and falls back to the Postgres implementation — the app degrades to its source of truth rather than to an error. Results are ids resolved against Postgres either way, so the index can lag (by at most the sync interval plus Elasticsearch's refresh interval) but can never show an item the database no longer has.

Deliberately not done: a dead-letter queue (rows retry indefinitely; `attempts` and `last_error` are the operator's signal), locking during reindex (an item changed mid-reindex is corrected by the next drain), replicas, and cluster security — the last two because this runs on a laptop.

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
    queries/      Read-side aggregations; returns rows, not entities
    search/       SearchService protocol, Postgres and Elasticsearch backends, outbox
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

Working: authentication, item CRUD with filtering and pagination, sales with profit calculation, full-text search with fuzzy matching on either Postgres or Elasticsearch, a dashboard computed entirely in SQL (profit over time, profit by marketplace, inventory aging), light and dark themes.

Not built yet: a scheduled market-price poller.

Deliberately out of scope, since this is not deployed publicly: email verification, password reset, refresh tokens, and rate limiting on the login endpoint. All four would be required before exposing it to real users.

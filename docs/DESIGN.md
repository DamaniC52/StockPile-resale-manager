# Stockpile — Data Model & Architecture

Design notes for the backend: what was decided, why, and what each choice costs.

## Domain

Resale sellers buy inventory and resell it across marketplaces (eBay, StockX, Depop, Grailed). FlipTrack tracks what they hold, what it cost, what it sold for, and what they actually made after fees.

| Table | Scope | Purpose |
|---|---|---|
| `users` | — | Tenant identity |
| `items` | tenant | A lot of N identical units with a per-unit cost |
| `listings` | tenant | A lot offered on one marketplace at one price |
| `sales` | tenant | Units leaving a lot, with the profit they produced |
| `products` | global | Shared catalog identity (brand, style code, size) |
| `marketplaces` | global | Lookup table for platforms |
| `price_snapshots` | global | Periodic market-price readings per product |

Tenant tables carry `user_id`. Global tables do not — market prices and catalog entries are facts about the world, not about a user.

## Decisions

### Quantity-based lots, not serialized inventory

One `items` row represents N identical units; sales draw partial quantities from it. The alternative — one row per physical unit — is more expressive and would be required for consignment or per-unit authentication tags.

*Cost:* no per-unit identity, and every write path needs quantity arithmetic.
*Mitigation:* anything needing unit-level tracking is a lot with `quantity = 1`.

### `quantity_remaining` is denormalized to make a constraint possible

It could be derived: `quantity - COALESCE(SUM(sales.quantity_sold), 0)`. That version can never drift, but it also cannot be constrained — a `CHECK` cannot reference another table, so overselling would be preventable only in application code.

Storing the counter makes `quantity_remaining >= 0` a row-local predicate, which Postgres enforces directly. Denormalization here buys a correctness guarantee rather than speed.

A generated column is not an option: Postgres requires generated expressions to be `IMMUTABLE` and reference only columns of the same row.

*Cost:* the counter can drift from `sales` if a write path forgets to update it.
*Mitigation:* all quantity changes go through `services/sales.py`, and an audit query compares stored against computed values.

### Cost basis is snapshotted onto each sale

`sales.unit_cost_snapshot` and `sales.acq_fee_allocated` are copied from the item at sale time and never recomputed. Correcting an item's cost in June must not change March's reported profit — the same reason an invoice line copies unit price instead of joining to a product table.

It also makes `sales` self-sufficient for PNL: every aggregation is a single-table `SUM` with no joins.

*Cost:* duplicated data, and item cost edits are explicitly not retroactive.

### Per-unit cost and flat fees stored separately

`unit_cost` plus `acquisition_fee_total`, not a lot total. A $100 lot of 3 has no exact per-unit cost, and a flat $20 inbound shipping charge should not change when a miscounted quantity is corrected.

Flat fees are allocated across sales with the final sale absorbing the remainder, so allocated shares sum to exactly the original fee over the lot's lifetime.

### No `status` column on items

With lots, a single enum is unrepresentable — "3 sold, 2 in stock, 1 listed" has no one value. Stock state is derived from `quantity` vs. `quantity_remaining` via a hybrid property. Listing state is stored on `listings`, where one row genuinely has one lifecycle.

### Multi-tenancy enforced by composite foreign keys

`user_id` is denormalized onto `listings` and `sales` so tenant filtering and the dashboard's date-range aggregation are single-table index scans.

The consistency risk that creates — a sale claiming user 4 while referencing an item owned by user 7 — is closed by a composite foreign key:

```sql
FOREIGN KEY (item_id, user_id) REFERENCES items(id, user_id)
```

Cross-tenant rows become unrepresentable; the database rejects them. This turns IDOR (OWASP API1: Broken Object Level Authorization) from a class of application bug into a constraint violation.

The API layer adds defense in depth: ownership-scoped routes resolve objects through a single dependency that filters on `user_id` and returns **404, not 403**, since 403 would confirm a row exists and belongs to someone else.

Postgres Row-Level Security would enforce this for ad-hoc queries too. Deferred: it requires per-connection session variables and a non-superuser role, and the composite FKs plus a disciplined dependency cover the realistic threat model.

### A sale's listing must belong to the same item

```sql
FOREIGN KEY (listing_id, item_id) REFERENCES listings(id, item_id)
```

`listing_id` is nullable because cash and off-platform sales have no listing. `MATCH SIMPLE` semantics skip the constraint when any key column is NULL, which is exactly the required behaviour.

### Money is `NUMERIC(12,2)` / `Decimal`

Never `float`. IEEE-754 binary floating point cannot represent `0.10`; Postgres `numeric` is exact base-10 and psycopg maps it to `decimal.Decimal`. Integer cents would also be exact but push `/ 100` into every query and serializer.

Pydantic serializes `Decimal` to a JSON string, which is kept deliberately — a client calling `JSON.parse` on a number would reintroduce float error.

### Profit is a hybrid property with a SQL expression

```
revenue    = unit_price * quantity_sold
cogs       = unit_cost_snapshot * quantity_sold + acq_fee_allocated
net_profit = revenue - platform_fee - shipping_cost - other_fees - cogs
```

Each is defined once, with both a Python body and a SQL expression. A plain Python property would force `SUM` to load every sale row into memory; the SQL form lets `func.sum(Sale.net_profit)` aggregate in the database.

A stored generated column would also work here (all inputs are same-row) but would require a migration and full table rewrite to change the formula.

### Listings are a first-class table

A lot can be listed on several marketplaces at different prices, and unsold listings are what make sell-through rate and time-to-sale computable. A partial unique index enforces at most one *active* listing per item per marketplace while allowing relisting.

Per-listing quantities are out of scope for v1: they would require preventing over-listing across marketplaces, a second concurrent-reservation problem.

### Price snapshots are keyed on product, not item

Market price is shared reference data. Keying on `item_id` would store the same public price once per owner, multiply API calls, and let copies diverge. Items with no catalog entry (`product_id IS NULL`) simply have no price tracking.

### Enums are `String` + `CHECK`, not native Postgres `ENUM`

Values cannot be removed from a Postgres enum, and `ALTER TYPE` interacts badly with transactional migrations. A `CHECK` constraint gives the same guarantee and is a one-line migration to change. `StrEnum` provides type safety in Python and Pydantic validates at the API boundary.

### Services, no repositories

SQLAlchemy's `Session` already implements Unit of Work and Identity Map; wrapping it in `ItemRepository.get_by_id()` would be method-for-method passthrough. The schema is deliberately Postgres-shaped (partial indexes, composite FKs, `DISTINCT ON`, `date_trunc`), so there is no backend to swap to. And the most important behaviours — the oversell guard, the CHECK constraints — are database behaviours that a mocked repository would let pass.

`services/` exists for a narrower reason: `record_sale` owns an invariant (decrement, snapshot, insert, atomically) that must live in exactly one place once both a REST endpoint and a CSV importer call it.

### Search: Postgres full-text first, Elasticsearch behind the same interface

Search sits behind a `SearchService` protocol. The first implementation uses `tsvector` + GIN with `pg_trgm` for partial matches, avoiding a second datastore and an index-sync problem before search exists at all. An Elasticsearch implementation slots in behind the same interface, selected by configuration.

## Indexes

Postgres does not automatically index foreign keys — only primary keys and unique constraints. Every index below serves a named query.

| Index | Query |
|---|---|
| `users (lower(email))` unique | Case-insensitive login |
| `items (user_id, purchased_at)` | Inventory list: filter and sort in one index |
| `items (user_id) WHERE quantity_remaining > 0` | Current inventory; stays small as lots sell out |
| `items (id, user_id)` unique | Referent for composite tenancy FKs |
| `sales (user_id, sold_at)` | Every PNL-over-time aggregation |
| `sales (item_id, user_id)` | Lot detail, fee allocation, FK cascade |
| `sales (marketplace_id, external_order_id)` unique | Idempotent order import |
| `listings (item_id, marketplace_id) WHERE status = active` | Business rule and the "is it listed" check |
| `price_snapshots (product_id, marketplace_id, captured_at DESC)` | Latest price, chart series, idempotent polling |
| `products (sku, size)` unique, NULLS NOT DISTINCT | Catalog dedup including missing style codes |

`captured_at DESC` is declared explicitly because the latest-price query sorts product and marketplace ascending with `captured_at` descending; a backwards index scan reverses all columns at once and cannot serve a mixed-direction sort. Single-column descending sorts such as `items.purchased_at` need no `DESC` for that reason.

Deferred until a query is measurably slow: a covering index on `sales` for index-only dashboard scans, a `pg_trgm` GIN index for partial-match search, and BRIN plus range partitioning on `price_snapshots`.

## Migrations

Alembic, with `target_metadata` pointed at the declarative base and the database URL read from application settings rather than `alembic.ini`, so no credentials are committed and the app and migrations cannot target different databases.

A naming convention on `MetaData` gives constraints deterministic names, which keeps autogenerated migrations reviewable. `compare_type` and `compare_server_default` are enabled — both are off by default and their absence silently misses column type and DEFAULT changes.

Migrations are reviewed before being applied, and the downgrade path is tested. `alembic check` fails if models and schema have drifted, suitable for CI.

Reference data is seeded by an idempotent script rather than a migration, so it stays editable as the schema evolves.

## Known limitations

- Item cost edits are not retroactive to recorded sales (deliberate).
- A listing represents the whole remaining lot; per-listing quantities are not modelled.
- Single currency. Real multi-currency requires a stored FX rate per transaction.
- Sales are hard-deleted; accounting-correct voiding would use a `voided_at` soft delete.
- No Row-Level Security; tenancy is enforced by composite FKs and the API layer.

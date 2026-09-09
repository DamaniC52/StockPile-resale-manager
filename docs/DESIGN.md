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

### Search: two backends behind one interface

`SearchService` is a `Protocol` with one method: ranked item ids for a query,
scoped to a user. `PostgresSearchService` is the default; `ElasticSearchService`
is selected with `SEARCH_BACKEND=elasticsearch`. Ids rather than rows,
deliberately: an external index has no ORM objects to return, and resolving
ids against Postgres means a result can be stale (an item indexed then deleted
simply drops out of the `IN()` lookup) but never wrong.

The behavioural test suite is parametrized over both backends. The same
assertions (stemming, prefix, typo, phrase, OR, exclusion, ranking, tenancy)
must pass against each, so a divergence is a failing test rather than a
surprise in production. That is what makes the interface real.

One rule lives above both backends, in `search/base.py`: fuzzy and prefix
matching run only for a single bare word. The exact branch honours `-dunk`;
the fuzzy branch, OR-ed in, would let "Nike Dunk Low Panda" back through
because the raw string is still similar to it. A query with spaces or
operators is one the user finished typing; fuzzy matching exists for the
half-typed word before that.

**Postgres.** A stored generated `tsvector` (name weighted A, source B, size C)
with a GIN index, `websearch_to_tsquery` for operators, `ts_rank_cd` for
proximity-aware ranking, and `pg_trgm` `word_similarity` for bare words. The
generated column qualifies where `quantity_remaining` did not: same-row inputs
and an `IMMUTABLE` expression (the two-argument `to_tsvector`; the one-argument
form reads a session setting and is only `STABLE`).

**Elasticsearch.** Explicit mappings with `dynamic: strict`, so an unexpected
field is an indexing error rather than a silently guessed type that cannot be
changed later. The `item_text` analyzer (lowercase, ASCII folding, English
stopwords, English stemmer) mirrors Postgres's `english` configuration so both
backends reduce "hoodies" and "Hoodie" to `hoodi`. `name.prefix` is an
edge-ngram subfield (2 to 15 chars) with a non-ngram search analyzer:
ngramming the query too would make "jo" match everything containing "j".
`user_id` is a `keyword` used in a `bool.filter` clause, a yes/no test with no
bearing on score, and filter clauses are cached. Field boosts
`name^3 source^2 size` mirror the tsvector weights. Queries use
`simple_query_string` (never raises on user input; supports phrases, `-`, and
`|`) plus, for bare words, a prefix match and `fuzziness: AUTO`.

The index is addressed through an alias. Reindexing builds
`stockpile-items-<ms>` from Postgres, refreshes it, and swaps the alias in a
single `_aliases` call: readers never see a half-built index, and a bad
mapping change is rolled back by swapping again. The old index is deleted after
the swap.

### Elasticsearch consistency: a transactional outbox

Writing to Postgres and then to the index is rejected. If the second write
fails, or the process dies between the two, the datastores diverge and nothing
records that they did.

Every item change instead writes a `search_outbox` row **in the same
transaction**: either both land or neither does. Only changes to indexed
columns (`name`, `source`, `size`) enqueue; a cost or quantity edit does not.
Deletion goes through `services.inventory.delete_lot` for the same reason:
the delete and its outbox row must commit together, which a router calling
`db.delete()` directly cannot guarantee.

A drainer applies pending rows:

- `SELECT ... FOR UPDATE SKIP LOCKED`: several drainers can run without
  double-applying or queueing on the same rows.
- Multiple rows for one item collapse to its final state.
- The document is read from Postgres at drain time, not stored on the row: the
  row says *this item changed*, the database says what it is now. An `index`
  row for an item deleted in the meantime becomes a delete.
- External versioning: each document's version is `updated_at` in epoch
  milliseconds with `version_type=external_gte`, so applying rows out of order
  or twice converges on the newest state. A 409 from a stale write and a 404
  from deleting a missing document are both treated as success; the index is
  already in the desired state.
- Rows are marked processed only on success. On failure `attempts` and
  `last_error` are recorded and the row stays pending; an unreachable cluster
  loses nothing.

The drainer runs inside the API process's lifespan every `SEARCH_SYNC_INTERVAL`
seconds. Because the outbox is the queue, moving it to a dedicated worker, or
several, changes nothing else. `python -m app.search.cli drain|reindex|status`
exposes the same operations to an operator.

Staleness is bounded: the index lags Postgres by at most the sync interval plus
Elasticsearch's refresh interval (1 s by default). Because results are ids
resolved against Postgres, the lag can hide a new item briefly but cannot show
a deleted one.

If the cluster is unreachable, `ElasticSearchService` logs a warning and
delegates to `PostgresSearchService`. An unreachable cluster at startup is
logged, not fatal. The application degrades to its source of truth rather than
to an error.

*Deliberately not done:* a dead-letter queue (rows retry indefinitely;
`attempts` and `last_error` are the operator's signal), locking during reindex
(an item changed mid-reindex is corrected by the next drain), replicas, and
cluster security, the last two because this runs on a laptop.

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
- Search outbox rows retry without limit; there is no dead-letter queue.

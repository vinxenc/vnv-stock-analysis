---
name: database-migrations
description: "Safe, reversible database migration patterns for PostgreSQL with Alembic: forward-only production changes, expand-contract zero-downtime renames, concurrent indexes, batched backfills. Use when writing a schema or data migration, adding a column or index to a large table, planning a rollback, or preparing a zero-downtime deploy."
metadata:
  origin: ECC
---

# Database Migration Patterns

Safe, reversible database schema changes for production systems.

## When to Activate

- Creating or altering database tables
- Adding/removing columns or indexes
- Running data migrations (backfill, transform)
- Planning zero-downtime schema changes
- Setting up migration tooling for a new project

## Core Principles

1. **Every change is a migration** — never alter production databases manually
2. **Migrations are forward-only in production** — rollbacks use new forward migrations
3. **Schema and data migrations are separate** — never mix DDL and DML in one migration
4. **Test migrations against production-sized data** — a migration that works on 100 rows may lock on 10M
5. **Migrations are immutable once deployed** — never edit a migration that has run in production

## Migration Safety Checklist

Before applying any migration:

- [ ] Migration has both UP and DOWN (or is explicitly marked irreversible)
- [ ] No full table locks on large tables (use concurrent operations)
- [ ] New columns have defaults or are nullable (never add NOT NULL without default)
- [ ] Indexes created concurrently (not inline with CREATE TABLE for existing tables)
- [ ] Data backfill is a separate migration from schema change
- [ ] Tested against a copy of production data
- [ ] Rollback plan documented

## PostgreSQL Patterns

### Adding a Column Safely

```sql
-- GOOD: Nullable column, no lock
ALTER TABLE users ADD COLUMN avatar_url TEXT;

-- GOOD: Column with default (Postgres 11+ is instant, no rewrite)
ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;

-- BAD: NOT NULL without default on existing table (requires full rewrite)
ALTER TABLE users ADD COLUMN role TEXT NOT NULL;
-- This locks the table and rewrites every row
```

### Adding an Index Without Downtime

```sql
-- BAD: Blocks writes on large tables
CREATE INDEX idx_users_email ON users (email);

-- GOOD: Non-blocking, allows concurrent writes
CREATE INDEX CONCURRENTLY idx_users_email ON users (email);

-- Note: CONCURRENTLY cannot run inside a transaction block
-- Most migration tools need special handling for this
```

### Renaming a Column (Zero-Downtime)

Never rename directly in production. Use the expand-contract pattern:

```sql
-- Step 1: Add new column (migration 001)
ALTER TABLE users ADD COLUMN display_name TEXT;

-- Step 2: Backfill data (migration 002, data migration)
UPDATE users SET display_name = username WHERE display_name IS NULL;

-- Step 3: Update application code to read/write both columns
-- Deploy application changes

-- Step 4: Stop writing to old column, drop it (migration 003)
ALTER TABLE users DROP COLUMN username;
```

### Removing a Column Safely

```sql
-- Step 1: Remove all application references to the column
-- Step 2: Deploy application without the column reference
-- Step 3: Drop column in next migration
ALTER TABLE orders DROP COLUMN legacy_status;
```

### Large Data Migrations

```sql
-- BAD: Updates all rows in one transaction (locks table)
UPDATE users SET normalized_email = LOWER(email);

-- GOOD: Batch update with progress
DO $$
DECLARE
  batch_size INT := 10000;
  rows_updated INT;
BEGIN
  LOOP
    UPDATE users
    SET normalized_email = LOWER(email)
    WHERE id IN (
      SELECT id FROM users
      WHERE normalized_email IS NULL
      LIMIT batch_size
      FOR UPDATE SKIP LOCKED
    );
    GET DIAGNOSTICS rows_updated = ROW_COUNT;
    RAISE NOTICE 'Updated % rows', rows_updated;
    EXIT WHEN rows_updated = 0;
    COMMIT;
  END LOOP;
END $$;
```

## Alembic (Python)

Migrations live in `migrations/versions/`, the database comes from `$DATABASE_URL` (see `migrations/env.py`).

### Workflow

```bash
# Create a migration from model changes, then READ it before applying
uv run alembic revision --autogenerate -m "add prices.adj_close"

# Apply all pending migrations
uv run alembic upgrade head

# Show the current revision / history
uv run alembic current
uv run alembic history --verbose

# Fails if the models and the migrations differ (use in CI)
uv run alembic check

# Print the SQL instead of running it (review a production change)
uv run alembic upgrade head --sql

# Empty migration for hand-written SQL or a data backfill
uv run alembic revision -m "backfill prices.adj_close"
```

Autogenerate misses some changes (renames look like drop + add, server defaults, CHECK constraints) and may emit
`sqlmodel.sql.sqltypes.AutoString()`: keep the `import sqlmodel`. Always review and edit the generated file.

### Adding a Column Safely

```python
def upgrade() -> None:
    op.add_column("prices", sa.Column("adj_close", sa.Float(), nullable=True))  # nullable first, backfill later


def downgrade() -> None:
    op.drop_column("prices", "adj_close")
```

### Adding an Index Without Downtime

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction, so leave Alembic's transaction first:

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index("ix_prices_date", "prices", ["date"], postgresql_concurrently=True, if_not_exists=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_prices_date", table_name="prices", postgresql_concurrently=True, if_exists=True)
```

### Batched Backfill (separate migration from the schema change)

```python
def upgrade() -> None:
    connection = op.get_bind()
    while True:
        updated = connection.execute(
            sa.text(
                """
                UPDATE prices SET adj_close = close
                WHERE (symbol, date) IN (
                    SELECT symbol, date FROM prices WHERE adj_close IS NULL LIMIT 10000 FOR UPDATE SKIP LOCKED
                )
                """
            )
        ).rowcount
        if updated == 0:
            break
```

Run the whole migration in one transaction only for small tables; for large ones wrap the loop in
`with op.get_context().autocommit_block():` so each batch commits and locks are released.

### Alembic Rules

- Never edit a migration that already ran in production: add a new one.
- One head only: after merging branches, `uv run alembic heads` must list one revision (else `alembic merge`).
- Write a real `downgrade()` or `raise NotImplementedError` to mark the migration irreversible.
- `alembic upgrade head` is idempotent, so the deploy job can run it on every release.
- Test on a throwaway database: `upgrade head`, `downgrade -1`, `upgrade head` again, then `alembic check`.

## Zero-Downtime Migration Strategy

For critical production changes, follow the expand-contract pattern:

```
Phase 1: EXPAND
  - Add new column/table (nullable or with default)
  - Deploy: app writes to BOTH old and new
  - Backfill existing data

Phase 2: MIGRATE
  - Deploy: app reads from NEW, writes to BOTH
  - Verify data consistency

Phase 3: CONTRACT
  - Deploy: app only uses NEW
  - Drop old column/table in separate migration
```

### Timeline Example

```
Day 1: Migration adds new_status column (nullable)
Day 1: Deploy app v2 — writes to both status and new_status
Day 2: Run backfill migration for existing rows
Day 3: Deploy app v3 — reads from new_status only
Day 7: Migration drops old status column
```

## Anti-Patterns

| Anti-Pattern | Why It Fails | Better Approach |
|-------------|-------------|-----------------|
| Manual SQL in production | No audit trail, unrepeatable | Always use migration files |
| Editing deployed migrations | Causes drift between environments | Create new migration instead |
| NOT NULL without default | Locks table, rewrites all rows | Add nullable, backfill, then add constraint |
| Inline index on large table | Blocks writes during build | CREATE INDEX CONCURRENTLY |
| Schema + data in one migration | Hard to rollback, long transactions | Separate migrations |
| Dropping column before removing code | Application errors on missing column | Remove code first, drop column next deploy |

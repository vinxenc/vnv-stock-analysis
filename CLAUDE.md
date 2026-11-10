# Project rules

## Local Postgres: one per worktree, only one running

Every worktree has its own `docker compose` project (named after the folder), but all of them publish `127.0.0.1:5432`, so two can never run together, and a container created while the port was taken has no port mapping at all (`docker ps` shows an empty Ports column, connections are refused).

When you start work in a new worktree, and whenever the database refuses connections:

1. Stop every other container on the port: `docker ps -q --filter publish=5432 | xargs -r docker stop`.
2. Recreate this worktree's one: `docker compose up -d --force-recreate --wait`.
3. Re-seed it: `DATABASE_URL=postgresql+psycopg://vnv:vnv@localhost:5432/vnv uv run alembic upgrade head` (the volume is per project, so a new worktree starts empty).
4. If the task needs today's prices, run the sync: `vn_stock_latest_price_retrieval` then `vn_stock_daily_price_store` (see README, "Run the analysis pipeline locally").

Use `docker compose exec -T postgres psql -U vnv -d vnv` for ad-hoc SQL; do not wrap SQL in throwaway Python.

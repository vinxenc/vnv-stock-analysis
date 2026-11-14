# Project rules

## Research goes to the `researcher` agent

The main session does not search on its own. Every lookup goes to the `researcher` subagent (`.claude/agents/researcher.md`, Haiku 5.5, read-only), which returns a short sourced summary:

- the codebase: architecture, who calls what, where a symbol or file lives, how two parts connect;
- web search, library or API docs, prices, versions, licences;
- read-only database queries and other read-only resources (Notion, Lucid, …).

Send independent questions to several researchers in parallel, in one message. Use what a researcher reports; do not repeat its search yourself, and only re-check the single line you are about to rely on or edit.

The main session still does these directly, because a subagent would cost more than it saves:

- reading a file it is about to edit (Edit needs it read), or one exact path it already knows;
- commands whose output decides the next step: tests, lint, `git status` / `diff` / `log` of its own work, `gh` for its own PR and runs;
- anything that writes: edits, commits, migrations, workflow changes.

## Local Postgres: one per worktree, only one running

Every worktree has its own `docker compose` project (named after the folder), but all of them publish `127.0.0.1:5432`, so two can never run together, and a container created while the port was taken has no port mapping at all (`docker ps` shows an empty Ports column, connections are refused).

When you start work in a new worktree, and whenever the database refuses connections:

1. Stop every other container on the port: `docker ps -q --filter publish=5432 | xargs -r docker stop`.
2. Recreate this worktree's one: `docker compose up -d --force-recreate --wait`.
3. Re-seed it: `DATABASE_URL=postgresql+psycopg://vnv:vnv@localhost:5432/vnv uv run alembic upgrade head` (the volume is per project, so a new worktree starts empty).
4. If the task needs today's prices, run the sync: `vn_stock_latest_price_retrieval` then `vn_stock_daily_price_store` (see README, "Run the analysis pipeline locally").

Use `docker compose exec -T postgres psql -U vnv -d vnv` for ad-hoc SQL; do not wrap SQL in throwaway Python.

## Table names: `vn_stock_<thing>`

Every table is named `vn_stock_` plus a snake_case noun: `vn_stock_prices`, `vn_stock_rankings`, `vn_stock_screen_history`. A new table follows it from its first migration. Renaming one is a new migration (`op.rename_table`, plus `ALTER INDEX ... RENAME` for its `<table>_pkey` and every `ix_<table>_<column>` index, since `alembic check` compares index names), never an edit of an applied migration, which keeps the old name. Migrations name tables as strings (`sa.table("prices", ...)`), never through the models, so an old revision still finds the table under the name it had then.

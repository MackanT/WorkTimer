# Migrations (v6 Postgres schema)

Numbered SQL files, applied in order by [src/migrator.py](../src/migrator.py),
each in its own transaction, and recorded in the `schema_migrations` table.

- **Name:** `NNNN_short_name.sql` — four digits, then lowercase letters,
  digits and underscores. The next number is one above the highest here.
- **Never edit a migration once it has been applied anywhere.** The runner
  stores a checksum and stops if the file changes. Change the schema with a
  new migration instead.
- **Never delete or renumber an applied migration.**
- If a merge leaves two files with the same number, or a new file numbered
  below one that is already applied, renumber the new one.
- Everything in a file runs in one transaction, so statements that can't run
  inside one (`CREATE INDEX CONCURRENTLY`, …) don't belong here.

Run by hand: `DATABASE_URL_ADMIN=… python -m src.migrator`.

## Rules for the schema

- **Run as the server's admin role.** `0001` creates the (server-wide) roles if
  they are missing; every object is created after `set local role
  worktimer_owner` and owned by it. End a file that switches role with
  `reset role;` — the runner records the migration afterwards, as itself.
- **A new user-data table** gets `fk_user integer not null default app_user()
  references users (key_user)`, row-level security enabled **and forced**, and
  the `tenant` policy (`using (fk_user = app_user())`).
- **Every unique or exclusion constraint on user data includes `fk_user`**, and
  foreign keys between user-data tables are composite: `(fk_user, fk_…)`
  referencing `(fk_user, key_…)`. FK and constraint checks see every user's
  rows; without `fk_user` they refuse — and name — another user's data.
- **Grant table by table.** Nothing is granted by default; a new table is
  invisible to `worktimer_app` and `worktimer_readonly` until its migration
  grants it. Credentials (`trackers.pat_token`) are never granted to
  `worktimer_readonly`.
- [tests/test_schema_v1.py](../tests/test_schema_v1.py) checks these rules for
  every table, so a table that misses one fails the suite.

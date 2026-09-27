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

Run by hand: `DATABASE_URL=… python -m src.migrator`.

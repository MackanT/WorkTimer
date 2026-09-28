# v6 implementation path

**Status:** r2 · 2026-09-28 — Phases 1 and 3 done; Phase 2 in progress (data layer, wiring, backups done); Phase 4 built; the Phase 0.4 manual click-through is still pending.
**Branch:** `feat/postgres-migration` (long-lived; one 6.0.0 release at the end).
**Design:** [v6_plan.md](v6_plan.md) covers *what* gets built and why. This file
is the *order* it gets built in, with a definition of done per step.

---

## The finding that reorders the work

The UI reaches the database through two channels:

| Channel | Volume | Nature |
|---|---|---|
| `function_db("method", …)` | 34 calls → 23 named `Database` methods | a real API |
| `query_db(sql)` | **53 raw SQL strings** in 10 files | SQLite dialect, old table and column names, in page code |
| `function_db("execute_query", sql)` | 3 more raw SQL strings | the same, routed through a method name |

Where the ~56 raw statements live:

| File | Raw SQL sites |
|---|---|
| `pages/time_tracking.py` | 15 |
| `pages/add_data.py` | 11 |
| `pages/reports.py` | 10 |
| `pages/tasks.py` | 5 |
| `ui/command_palette.py` | 4 |
| `pages/query_editor.py` | 3 (+3 `execute_query`) |
| `pages/root.py` | 2 |
| `globals.py`, `pages/board.py`, `ui/work_item_forms.py` | 1 each |

Porting in place would mean rewriting SQL across eleven files *while*
changing the dialect, the schema and every name — with no stable seam to test
against. So the first job is to move every statement behind the `Database`
API **while still on SQLite**. After that, the Postgres port happens behind one
API, and the characterisation tests pinned to that API become the oracle for
it.

---

## Overview

Everything lands on `feat/postgres-migration`; `main` gets one 6.0.0 at the end.

| Phase | Content | Behaviour change | Size |
|---|---|---|---|
| **0** | Characterisation tests, SQL consolidation, one clock | none | L |
| **1** | Postgres foundation: compose, deps, schema v1, RLS, connection layer | none (unused yet) | M |
| **2** | Port the data layer onto the new schema | the planned ones only | L |
| **3** | Query editor lockdown | yes | S |
| **4** | SQLite importer | new feature | M |
| **5** | **Gate:** single-user staging + parallel run on real data | — | M |
| **6** | Online: identity + per-user runtime state | login appears | M–L |
| **7** | Release 6.0.0 | — | S |

**Phase 5 is a gate, not a formality.** Billing numbers are proven on the new
schema *before* multi-user is layered on. If a total is wrong after Phase 6
starts, there must only be one possible cause.

**Long-lived-branch hygiene:** merge `main` into the branch whenever a 5.1.x fix
lands there; keep the suite green at every commit; one commit per logical step
so the history doubles as a changelog source.

---

## Phase 0 — Groundwork on SQLite

### 0.1 Characterisation tests: billing core

Pin today's behaviour, using the existing `db` fixture (fresh SQLite per test).
New files named `test_char_*.py` so the oracle set is easy to find and run on
its own.

Assert on **outputs of public `Database` methods** — never on SQL text,
triggers or column internals, which all change in Phase 2. Tolerances express
the business contract, so the same tests survive the float → `numeric` move:
hours to within a millisecond, money to within half an öre.

Cases:
- known start/end → `total_time`, `cost`, `user_bonus`
- **invariant:** a wage change after entries exist leaves their `cost`
  unchanged
- back-dated entry after a raise → pins *today's* wage choice (version at
  creation) and bonus choice (by date). Phase 2 changes the wage half
  deliberately; this test is where that diff gets reviewed.
- bonus period boundaries: inclusive start and end, open-ended `end_date`
- `dates.week` across New Year (e.g. 2026-12-28 → 2027-01-04)
- an entry spanning midnight → its `date_key`
- customer rename / disable / enable → effect on reads

**Done when:** all pass on current SQLite.

**Status: done** — [tests/test_char_billing.py](../tests/test_char_billing.py),
18 tests. Mutation-checked: a 0.1% cost error fails 5 of them, and edits
re-pricing at the current wage fails the snapshot test written for it. Report
aggregates get their characterisation tests in 0.2, as their SQL moves.

### 0.2 Move all SQL behind the `Database` API

Per file: extract each statement **verbatim** into a named `Database` method
(same SQL, same parameters, same return shape), replace the call site, then pin
the new method with a characterisation test. **No SQL rewriting in this
step** — moving and rewriting at once hides mistakes.

Order, by risk: `reports.py` (billing aggregates) → `time_tracking.py` (core
flow) → `add_data.py` → `tasks.py` → `command_palette.py` → the singles →
the three `execute_query` calls.

The query editor is the one legitimate raw-SQL path — it runs the *user's*
SQL. It moves behind a dedicated `run_user_query` method, making the special
case explicit, and `query_db` is removed.

Add an **architecture test** that scans `src/` and fails if SQL appears outside
the data layer, so the boundary cannot erode after this.

One commit per file; suite green after each.

**Done when:** no page or UI module contains SQL; the architecture test
passes.

**Progress:**

| File | Status |
|---|---|
| `pages/reports.py` | **done** — 10 statements → 7 methods (`get_current_customers`, `report_totals`, `report_hours_for_rounding`, `report_hours_by_project` / `_customer` / `_day` / `_work_item`). Proven frame-identical to the original SQL, dtypes included (108 comparisons); pinned in [tests/test_char_reports.py](../tests/test_char_reports.py) (15 tests, mutation-checked). |
| `pages/time_tracking.py` | **done** — 15 statements → 10 new methods + 2 reused (`get_current_customers`, `get_customer_name`); repeats collapsed (the name lookup appeared 3×, the running-timer check 2×). Proven identical to the original SQL (260 comparisons, incl. nonexistent ids); pinned in [tests/test_char_time_tracking.py](../tests/test_char_time_tracking.py) (12 tests, mutation-checked). |
| `pages/add_data.py` | **done** — 11 statements → 8 methods (the current-customer-name lookup appeared 3×; both enabled-project queries share one). Proven identical (10 comparisons); pinned in [tests/test_char_entity_dialogs.py](../tests/test_char_entity_dialogs.py) (7 tests, mutation-checked). |
| `pages/tasks.py` | **done** — 5 statements → 2 new methods (`get_tasks`, `get_task_titles`) + 3 reused; the page's `SORT_QUERIES` map moved verbatim to `Database.TASK_SORTS` (still the toolbar's single source of truth; `test_tasks_logic.py` retargeted). Proven identical (28 comparisons; the map is identical up to whitespace inside the two multi-line priority clauses). Pinned in [tests/test_char_tasks.py](../tests/test_char_tasks.py) (8 tests, mutation-checked — incl. a simulated Postgres NULL order). |
| `ui/command_palette.py` | **done** — 4 statements → 2 new methods (`get_running_timers_with_names`, `get_current_customer_projects`) + 2 reused (`get_running_timer_names` — the same query as the Time page's indicator — and `get_current_customers`). Proven identical (4 comparisons); pinned in [tests/test_char_command_palette.py](../tests/test_char_command_palette.py) (2 tests, mutation-checked). |
| `root.py`, `globals.py`, `board.py`, `work_item_forms.py` | **done** — 5 statements → 3 new methods (`get_tracker_expiries`, `get_devops_watermarks`, `get_customer_color`) + 2 reused. Proven identical (8 comparisons); pinned in [tests/test_char_sync_and_shell.py](../tests/test_char_sync_and_shell.py) (3 tests, mutation-checked). |
| `pages/query_editor.py` | **done** — user SQL behind `run_user_query` / `check_user_query`; saved-query writes → `insert_` / `update_` / `delete_saved_query`; the fallback starter SQL → `Database.EDITOR_FALLBACK_QUERY`; the row-edit lookup moved with 5.1.2. `QueryEngine.query_db` **removed** — no callers left. Proven identical (8 comparisons); pinned in [tests/test_char_query_editor.py](../tests/test_char_query_editor.py) (5 tests; one — user SQL can write — changes in Phase 3). |
| `pages/settings.py` | **done** — found by the architecture test, not the original count: it called `core.query_engine.db.fetch_query(...)` directly, bypassing `query_db`. → `get_tracker_types`. |

**Status: done.** No page, UI or service module contains SQL against a
WorkTimer table; [tests/test_architecture.py](../tests/test_architecture.py)
enforces it (and caught a planted leak). Its table list holds today's names —
Phase 2 must add the renamed tables. The one remaining SQL-looking string
outside the data layer is the SQL-editor theme preview in Settings: sample
text, never executed.

**Live 5.1.1 bugs found during 0.2** (same SCD2 root cause) — **fixed in 5.1.2**
(`fix/5_1_2`, merged into this branch; `main` pending), with regression tests
`test_raise_keeps_customer_settings.py` and `test_row_edit_after_raise.py`:

- **A raise resets the customer's per-customer settings.** The add-customer
  form creates the new version row from its own fields and carries over only
  the tracker link — so colour, expected work % and **tracker project** are
  cleared. With no project configured, the DevOps provider silently falls back
  to the organisation's *first* project: board, sync and new work items move
  to the wrong project.
- **Query-editor row edit of an entry logged before a raise.** The project
  dropdown is empty (it asks with the entry's old customer id), and at the
  database layer an Update resolves the project by name under that old id,
  finds nothing and writes `project_id = 0` — the entry drops out of the Time
  Tracker. Whether the dialog lets that save through is untested in the UI.

### 0.3 One clock

A small `clock` module (`now_local()`, `today_local()`), initially returning
exactly what `datetime.now()` returns today. Route the 22 `datetime.now()`
sites (7 files) that concern user time through it. The update checker's cache
timestamp can stay as it is.

No behaviour change now; in Phase 2 the switch to UTC storage with local
presentation becomes a change to one module rather than a hunt.

**Status: done.** [src/clock.py](../src/clock.py) (`now_local()`,
`today_local()`). The real inventory was 41 clock reads in 14 files (the "22"
above counted only `datetime.now()`):

- **29 routed through the clock** — timer start/stop and stored timestamps
  (`database.py`), last-sync times (`globals.py`), date-range presets and
  "today" defaults (`helpers.py`, `add_data.py`, `reports.py`,
  `dynamic_widgets.py`), the Time Tracker (`time_tracking.py`), and
  `root.py`'s once-a-day token warning.
- **12 deliberately left on the standard library** — the 2 AM sync scheduler,
  export/backup/image filenames, the update-check cache age, the tracker retry
  cooldown. In v6 "local" means the *user's* timezone, the wrong clock for
  server housekeeping.

Enforced by `test_calendar_time_is_read_through_src_clock` in
[tests/test_architecture.py](../tests/test_architecture.py): technical reads
are allowlisted per function with a reason, stale allowlist entries fail too,
and a planted `datetime.now()` was caught. [tests/test_clock.py](../tests/test_clock.py)
freezes the clock to prove the timer and date presets read it.

**For Phase 2 — five "now"s inside SQL** (all in `database.py`, so the clock
can't reach them without changing the SQL): the running-timer durations in
`get_customer_ui_list` (2×) and `_REPORT_DUR`, and `get_recent_project_hours`
(2×). Pass the clock's value as a parameter instead. Note that
`get_recent_project_hours`' `date('now', '-60 days')` is **UTC** while its
neighbours use `'localtime'` — the 60-day window is off by the UTC offset
around midnight today.

### 0.4 Checkpoint

Full suite green; the app smoke-tested by hand against a copy of a real 5.x
database. Phase 0 is the last point where the branch is behaviourally identical
to `main`.

**Automated part — done** (against a seeded copy; the checkout's own
`data/worktimer.db` turned out to be empty, so a *real* database is still to
come):

- The app boots against the copy (tracker credentials blanked in the copy, so
  no outbound tracker calls), all ten routes answer 200, no errors logged.
- A throwaway page smoke test using NiceGUI's simulated `user` fixture opened
  all nine pages: each built without an ERROR log, and seeded data rendered
  where checked (Time Tracker, Tasks, Query editor). It waits for each page's
  async build task — without that, pages returned before their data loaded and
  a broken `report_totals` went unnoticed. Mutation-checked: a failing
  `get_running_timers`, `get_tasks`, `report_totals` or
  `get_current_customers` fails its page. Not covered: interactions (e.g. Run
  in the query editor) and reads wrapped in a deliberate `try/except` fallback.
- Afterwards: row counts unchanged, no schema drift.

**Against the real database** (a snapshot; the original only ever read, tracker
credentials blanked in the copy) — 4,467 entries, Oct 2023 → Sep 2026:

- **Phase 0 is behaviour-identical on real data:** every statement moved in
  0.2, run in its original form next to its new method, across all 10
  customers, 57 projects, six date ranges and every task sort — **4,798
  comparisons, 0 mismatches**.
- **Stored billing is internally consistent:** in all 4,466 completed entries,
  duration = end − start, cost = wage × hours and user bonus agree. A clean
  baseline for the Phase 4 importer and the Phase 5 parallel run.
- All nine pages build without errors; afterwards row counts, stored billing
  totals and the schema are unchanged.
- Live bug exposure: no orphaned timer, no settings wiped by a raise; **616
  entries logged before a raise** (so the pinned "Manage entries" / "Sort by
  usage" bugs do affect real use); untagged time stored as both `0` (2,017)
  and `NULL` (545), so the per-work-item rounding split is live.
- **9 entries (7.25 h, Jan–Mar 2025) have `project_id = 0`** but still carry
  their project *name*; each maps to exactly one project of that name under
  its customer. They count in Reports (grouped by name) but queries joining
  on the project id skip them. **Re-linked by 5.1.2** — verified on a
  snapshot: exactly these 9, only `project_id` changed, every other table and
  the billing totals identical. (Their projects are all *disabled*, so the
  Time Tracker, which lists enabled projects only, never showed them either
  way — the repair fixes the data, not a visible total.)
- Harness note: `src/core/app.py`'s module-level `_global_tracker_init_lock`
  binds to the first event loop that uses it, so tests must share one loop.
  Production has one loop per process, so it's not an app bug — but the task
  it lives in is fire-and-forget without error handling, and these
  process-wide singletons are exactly what Phase 6 restructures.

**Page smoke test — now permanent:**
[tests/test_smoke_pages.py](../tests/test_smoke_pages.py) opens all nine pages
as NiceGUI's simulated user against a seeded temp database (dev dependency
`pytest-asyncio`; `asyncio_mode = "auto"` in `pyproject.toml`). It runs offline
(update check and internet probe stubbed) and is guarded two ways, both
proven: NiceGUI's test fixtures *delete* every `storage-*.json` in their
storage directory, so the root [conftest.py](../conftest.py) redirects
`NICEGUI_STORAGE_PATH` before NiceGUI is imported and the test refuses to run
if storage still points at the real `.nicegui/`; and teardown fails if
`data/worktimer.db` was opened. Phase 2: once the app runs on Postgres, seed
through `pg_db` instead of a temp SQLite file — the test itself doesn't
change.

**Manual click-through — pending.** On your real setup, the flows Phase 0 and
5.1.1/5.1.2 touched:

- [ ] **Time Tracker** — start and stop a timer by checkbox; the stop dialog
  (comment, move to another project, back-dated stop); manual entry; manual
  start; *Manage entries* edit and delete; *Sort by usage*; *Edit Order* and
  save; the date presets incl. All-Time; customer colour dots.
- [ ] **Customer / project / tracker / bonus dialogs** — every tab; a raise
  (re-add a customer with a new wage) keeps its colour, expected % and
  tracker project; tracker *Test connection*.
- [ ] **Reports** — periods, customer filter, each rounding basis, CSV export.
- [ ] **Tasks** — every sort, *show completed*, add / edit / complete / delete,
  the task picker.
- [ ] **Board** — loads for a tracker customer, colours shown.
- [ ] **Command palette** (Ctrl+K) — start and stop a timer, backup.
- [ ] **Query editor** — run a query; save, update and delete a saved query;
  invalid SQL refused on save; row edit of a time entry, incl. one logged
  before a raise.
- [ ] **Settings** — tracker form-defaults lists your trackers; backup and
  download; last-sync times.
- [ ] **App shell** — running-timer pills in the nav bar; token-expiry
  warning; the *What's new* dialog.

---

## Phase 1 — Postgres foundation

### 1.1 Local Postgres and a test fixture

- `docker-compose.yml` gains a `postgres` service: official image, pinned
  major version, named volume, healthcheck; the app waits on
  `condition: service_healthy`.
- A `pg_db` test fixture giving each test a fresh database (from a template,
  for speed). Postgres tests are marked so the SQLite suite still runs
  without Docker during the transition.

**Status: done** (the app doesn't use Postgres yet; `depends_on` arrives with
the port).

- `postgres:18` service, published on **`127.0.0.1` only**, data in the named
  volume `pgdata` mounted at `/var/lib/postgresql` (the Postgres 18 layout),
  `pg_isready` healthcheck, dev password default `worktimer-dev`
  (`POSTGRES_PASSWORD` in `.env` overrides — Phase 7 must require a real one
  for hosted installs). Start it: `docker compose up -d postgres`; with Docker
  in WSL, `wsl docker compose up -d postgres` in the repo.
- **Not `testcontainers`.** With Docker inside WSL, Windows-side Python could
  only drive the daemon if it were exposed over unauthenticated TCP —
  root-equivalent for any local process. Instead the fixtures in
  [tests/conftest.py](../tests/conftest.py) use the running dev server:
  `pg_server` (skips with a start hint when it's down; sweeps `wt_test_*`
  leftovers from crashed runs) and `pg_db` (a fresh database per test, dropped
  afterwards). Tests need only a connection URL (`WORKTIMER_TEST_PG_URL`
  overrides the default). Template-cloning for speed comes with the schema.
- Verified: PostgreSQL 18.6, `btree_gist` available, server clock UTC;
  reachable on `127.0.0.1:5432`, **refused on the LAN address** (this machine
  runs WSL in mirrored networking mode, where an all-interfaces port mapping
  would expose it); tests skip cleanly with the server down; no databases left
  behind after a run. [tests/test_pg_fixture.py](../tests/test_pg_fixture.py)
  pins the server requirements and per-test isolation.
- `psycopg[binary]` and `psycopg-pool` added now (the fixture needs the driver).

### 1.2 Dependencies and migrations

- `psycopg[binary]` and `psycopg-pool`.
- **Migrations: numbered SQL files** (`migrations/NNNN_name.sql`) applied by a
  small runner, each file in its own transaction, recorded in a
  `schema_migrations` table; applied on startup. The runner connects as the
  server's admin role — `0001` provisions the roles — and every schema object
  is owned by `worktimer_owner` (1.3).

**Status: done** (the runner exists; wiring it into app startup comes with
the port, and there are no migrations yet — `0001` is 1.3).

- [src/migrator.py](../src/migrator.py): `migrate(conninfo)` applies pending
  files in order, each in one transaction together with its
  `schema_migrations` row (version, name, sha256, `applied_at`); a failing
  file rolls back whole and nothing after it runs. Command line:
  `DATABASE_URL_ADMIN=… python -m src.migrator`.
- **Refuses rather than guesses** when a `.sql` file is misnamed, two files
  share a number, an applied file was edited (checksum) or deleted, or a new
  file is numbered below the newest applied one (two branches both took the
  next number). The checksum normalises line endings, so a Windows (CRLF)
  checkout and a Linux (LF) image agree.
- A **Postgres advisory lock** serialises concurrent runs (two app instances
  starting at once).
- Conventions in [migrations/README.md](../migrations/README.md).
- [tests/test_migrator.py](../tests/test_migrator.py): 14 tests (discovery
  offline; applying, reruns, rollback, the refusals and concurrency on a
  throwaway Postgres database). Mutation-checked: without the history check 3
  tests fail; without the lock the concurrency test fails.
- The architecture guard counts the runner as data layer (it creates its own
  history table).

### 1.3 Schema v1 (migration `0001`)

Everything in [v6_plan.md §5](v6_plan.md): tables, FK actions, unique
constraints including `fk_user`, partial uniques on soft-deleted tables,
exclusion constraints (`btree_gist`), the `dates` view, `v_time_entries`
(`security_invoker`), the three roles, RLS enabled and forced on every tenant
table, and user 1 (`bk_user = 'local'`).

**Security tests, written now — before any app code touches the schema.**
These are the most important tests in the project:
- no `app.user_id` set → zero rows from every tenant table (fails closed)
- user 1 cannot read, update or delete user 2's rows
- `worktimer_readonly` cannot write
- `worktimer_app` cannot bypass RLS
- overlapping wage periods for one customer are rejected
- deleting a customer or project with time entries is refused

**Status: done** (nothing in the app uses the schema yet).

- [migrations/0001_schema_v1.sql](../migrations/0001_schema_v1.sql): the §5
  tables, `dates` (a `generate_series` view, 2000–2100, pure date arithmetic so
  the session time zone can't shift a day) and `v_time_entries`
  (`security_invoker`); RLS enabled **and forced** on `users` (own row) and all
  nine user-data tables; user 1 (`local`).
- **Roles:** created only if missing (roles are server-wide, shared by every
  database on the server) and `NOLOGIN` — logins and passwords are deployment
  configuration, set in 1.4, never in a checked-in file. So the runner needs a
  role that can create roles (the compose `postgres` admin); the migration
  switches to `worktimer_owner` for everything it creates. It **refuses** to
  continue if `worktimer_app` or `worktimer_readonly` is a superuser or has
  `BYPASSRLS`.
- **Beyond §5, found or decided while building:**
  - Foreign keys between user-data tables are **composite, `(fk_user, fk_…)`**.
    FK checks bypass RLS, so a plain `fk_customer` would let user 1 attach a
    project to user 2's customer just by knowing its key.
  - The wage **exclusion constraint includes `fk_user`** — the "every unique
    constraint includes `fk_user`" rule applies to exclusion constraints too.
    Without it, user 1's insert collided with user 2's wage period before the
    FK refused it, and the error named user 2's dates. A test caught this;
    structural tests now check every unique/exclusion rule and every foreign
    key between user-data tables.
  - Wage and bonus periods treat `valid_to` as **inclusive** (the last day, as
    in 5.x), so the ranges are `'[]'`.
  - The currency lock (§4) is a trigger: changing a customer's currency is
    refused once it has time entries (soft-deleted ones included).
  - `trackers.pat_token` accepts only `enc:` ciphertext (or empty).
  - The read-only role gets every tracker column **except** `pat_token`.
  - `updated_at` / `updated_by` are set by a trigger; `created_by`, `updated_by`
    and `fk_user` default to the transaction's user.
  - Deletes refused by time entries raise `RestrictViolation` (23001) — the
    code Phase 2 step 7 maps to "has N time entries — disable instead".
- [tests/test_schema_v1.py](../tests/test_schema_v1.py): 34 tests, each on a
  fresh copy of the migrated schema (`pg_schema_db`, cloned from a template
  migrated once per session). Every check runs as the real role
  (`SET LOCAL ROLE`) with `app.user_id` set the way the app will. Besides the
  six above: rows can't reference another user's rows; nothing can be written
  without a user; the read-only role can't read credentials; the app role
  can't switch RLS off, disable or drop it; unique names per user; the
  currency lock; `v_time_entries`; ISO weeks at New Year; the migration
  applies to a second database on the same server.
- **Mutation-checked:** without `FORCE` 2 tests fail; without `fk_user` in a
  foreign key or in the wage exclusion, 1 and 2; without the bypass-RLS
  refusal, 1; with `pat_token` granted to the read-only role, 1.
- **Left for 1.4:** membership (`SET ROLE`) is checked against the session
  user, so these tests assert "the app roles are members of nothing" from the
  catalog; the connection layer's integration test logs in as the real role.

### 1.4 Connection layer

A pool plus a single `transaction(user_key)` context manager:
`BEGIN` → `SET LOCAL app.user_id` → work → `COMMIT` / `ROLLBACK`. This is the
**only** place `SET LOCAL` appears. Config: `DATABASE_URL` (app role) and
`DATABASE_URL_READONLY`; in single-user mode the user key resolves to 1.

**Done when:** an integration test writes and reads through the pool with RLS
on, and all security tests pass.

**Status: done** (the app doesn't use it yet — Phase 2 builds the Postgres
`Database` on it).

- [src/pg_connection.py](../src/pg_connection.py): `Pools` (psycopg-pool,
  thread-safe for the worker threads `function_db` runs in) and
  `Pools.transaction(user_key, readonly=False)`. The user is set with
  `SET LOCAL app.user_id` (until Phase 3 it was `set_config(…, true)`, which
  no role may call since migration 0002). Nothing hands out a bare connection. A user key that isn't a
  positive int is refused before a connection is taken. Pooled sessions run in
  UTC. `LOCAL_USER = 1` for single-user mode.
- **Config:** `DATABASE_URL` (worktimer_app) and `DATABASE_URL_READONLY`
  (worktimer_readonly; required only for read-only transactions). The
  migrator moved to **`DATABASE_URL_ADMIN`**: since `0001` it has to run as the
  admin role, so it can't share the app's URL.
- **Logins:** the roles stay `NOLOGIN` in the schema. Tests give them random
  per-session passwords (`pg_logins`) and take the login away afterwards;
  provisioning real logins is part of wiring compose in Phase 2.
- [tests/test_pg_connection.py](../tests/test_pg_connection.py): 15 tests
  logged in as the real roles — the integration test (write and read through
  the pool, RLS on, two users), the setting ends with its transaction on the
  same pooled session, errors roll back whole and the session recovers,
  read-only writes nothing and can't read credentials, the app role's own login
  can't switch RLS off or `SET ROLE` to the owner or the admin (the check 1.3
  left open), bad user keys, UTC, config from the environment.
- The architecture guard now allows `app.user_id`, `SET LOCAL` and
  `set_config(` only in the connection layer.
- **Mutation-checked:** with a session-wide setting (`is_local => false`) the
  leak test fails; without the explicit transaction 4 tests fail; a user
  setting planted in another module fails the guard.

---

## Phase 2 — Port the data layer

A Postgres implementation of the same public `Database` API. The `db` fixture
switches to it, and the Phase 0 characterisation tests run **unchanged** as the
oracle — except for reviewed diffs, each already marked in its test:

- **Planned:** cost rounded to öre; wage looked up by entry date.
- **Pinned quirks, fix pending your call** (both found in 0.2, both fall out
  of the new schema naturally):
  - per-project billing rounding groups by project *name*, so two customers'
    same-named projects round as one unit;
  - "no work item" is `0` from manual entries but `NULL` from stopped timers,
    so per-work-item rounding splits untagged time into two units;
  - entity-dialog customer dropdowns follow SQLite's row order — creation
    order, with a wage change moving the customer last. Postgres guarantees no
    order, so this one *must* be decided (alphabetical or the user's sort
    order).
- **Pinned bugs, fixed by the new schema** (found in 0.2; one root cause — a
  wage change issues a new `customer_id`, entries keep the old one, and the
  Time Tracker asks with the current one). Phase 2 looks entries up through the
  project, so each expectation flips:
  - ~~a timer **running across a wage change** is invisible to the tracker;
    ticking it starts a second timer while the first runs on~~ — **fixed
    early in 5.1.1** (`insert_customer` moves running timers with the
    projects, plus a startup repair); its test now pins the fixed behaviour;
  - **"Manage entries"** omits entries logged before a raise;
  - **"Sort by usage"** ignores usage logged before a raise;
  - a disabled project **cannot be re-enabled** from the dialog while another
    customer has an enabled project of the same name (matched by name, not
    key).

**Return shapes keep today's column names**, aliased in the SQL
(`duration_hours as total_time`), so no page changes during the port. The
*stored* schema is fully clean — that is what persists. The in-memory names can
be modernised later at no risk, since nothing stores them.

Steps:

1. **Time-entry write path** (replaces the three triggers): one function
   computes the exact duration, the local `fk_date`, looks up wage
   (`customer_wages`) and bonus by that date, snapshots both, and rounds cost
   once. Insert, stop-timer, "Manage entries" edit and project reassignment all
   go through it.
2. **Query-editor row edits go through it too.** Today the row-edit dialog
   saves `time` rows via `update_data_from_query`, a generic
   `UPDATE "time" SET start_time = …`, and the SQLite trigger silently
   recomputes the cost afterwards. Without triggers, that same edit leaves the
   cost **stale — a silently wrong invoice.** The generic update builder goes
   away; each editable table routes to its entity method. Test: editing start
   or end through the row dialog recomputes cost. (Customer and project row
   edits only expose colour, expected % and default work item — Type 1
   fields, already safe.)
3. **Customers:** `customers` + `customer_wages`. Wage change appends a row;
   rename is one row; disable and enable flip `is_enabled`. Currency field in
   the customer dialog, locked once entries exist.
4. **Everything else**, method by method: projects, bonuses, tasks, trackers,
   saved queries, and the tracker sync's writes into `work_items`.
5. **Reads and reports:** port the (now consolidated) report queries to
   Postgres dialect; totals per currency; soft-deleted rows excluded. **Every
   query without an `ORDER BY` gets one** — Postgres guarantees no row order,
   and SQLite's incidental order is what users see today. Phase 0.2 marks
   these methods "(unordered)" in their docstrings; where the order is
   visible (dialog dropdowns), choose it deliberately. **NULL ordering
   flips:** SQLite sorts NULLs first in ascending order, Postgres last. Every
   `ORDER BY` on a nullable column needs an explicit `NULLS FIRST` to keep
   today's order — the Tasks "Status", "Customer" and "Project" sorts are the
   known cases, pinned in `test_char_tasks.py`.
6. **Timestamps:** UTC storage; local presentation through `clock` and
   `users.timezone`.
7. **Delete semantics:** soft delete where the plan says; hard delete for
   customers and projects, with the FK refusal shown as "has N time entries —
   disable instead".
8. **Backup:** `pg_dump`; the app image installs `postgresql-client`.
   *(Decided 2026-09-28: split in two — see the status below.)*
9. **Remove from the runtime path:** the SQLite `Database` class (kept only for
   the importer), triggers, `validate_and_migrate_schema`, the `dates` horizon
   code.

**Done when:** the full suite passes on Postgres; the characterisation diffs are
exactly the two approved ones; the app runs end to end under compose.

**Status: in progress** — the data layer is ported, passes the oracle and is
wired in (Postgres when `DATABASE_URL` is set); only step 9 remains, at
release (SQLite is the fallback until then).

- **Decided (2026-09-28):** customer dropdowns follow the Time Tracker order;
  per-work-item rounding pools all untagged time; per-project rounding groups
  by project. So the "exactly two approved diffs" above became the reviewed
  diffs listed below.
- [src/pg_database.py](../src/pg_database.py): `PgDatabase`, the same public
  API as `Database` on the v6 schema, one `Pools.transaction` per call for its
  user. 78 of the 91 public methods. Not ported, by design: the SQLite
  machinery (`validate_and_migrate_schema`, `get_expected_schema`,
  `get_schema_info`, `compare_schemas`, `generate_sync_sql`, `smart_query` —
  the importer keeps them), `run_user_query` / `check_user_query` (Phase 3)
  and `backup_to` (step 8).
- **The oracle runs on both backends.** `pytest.mark.backends("sqlite",
  "postgres")` parametrizes the `db` fixture ([tests/conftest.py](../tests/conftest.py)).
  All eight characterisation modules carry it — 139 tests — except the query
  editor's two user-SQL tests, which Phase 3 changes.
- **Reviewed diffs**, each marked `REVIEWED DIFF` in its test: wage by the
  entry's date; "Manage entries" through the project; dropdown order; a
  disabled project can be re-enabled whatever others are called; per-project
  and per-work-item rounding; and a wage change keeps the customer's key (the
  running-timer test asserted the old id went stale).
- **Decisions made while porting:**
  - Step 1's snapshots are looked up again only when an entry moves to another
    day; any other edit keeps them, so an unrelated edit can't re-price history.
    A stop or edit writes the times and the cost in one statement.
  - Before a customer's first wage period, the first wage applies. A raise
    must start after the current period began — anything else would overlap
    history, so it is refused.
  - Time entries, tasks and saved queries are soft-deleted; discarding a running
    timer is a soft delete too.
  - Names sort with `collate "C"`, SQLite's byte order.
  - Tasks and cached work items must name real customers and projects (their
    fixtures now create them). Work-item writes are upserts; rows for an
    unknown customer are skipped with a warning.
  - "Now" on the user's calendar: `clock.now_in(users.timezone)`.
  - The PAT key stays in `data/.pat_key` (`secrets_dir`).
- [tests/test_pg_database.py](../tests/test_pg_database.py): 18 tests of what
  only Postgres does — local dating after midnight, both DST changes billed in
  real hours, the user's timezone, cost from the exact duration, the wage
  fallback and raise refusal, snapshots surviving edits, soft delete, the row
  edit re-pricing (step 2's required test), the work-item cache, one instance
  per user.
- **Mutation-checked:** wage by the latest period instead of the entry's date,
  and reports counting deleted entries, each fail a test. Skipping the Python
  rounding does not: the `numeric(12,2)` columns round identically.
- **Wired in — Postgres only when configured** (decided 2026-09-28):
  `QueryEngine` opens `PgDatabase` when `DATABASE_URL` is set and SQLite
  otherwise, so a 5.x setup built from this branch keeps working on its own
  data until the importer (Phase 4). On Postgres the SQLite path's folder
  still holds the PAT key and backups. The startup banner names the database
  (never the password).
  - **Compose profile `postgres`**: `docker compose --profile postgres up -d
    --build` adds a one-shot `migrate` service and `worktimer-pg` on port
    8090 (own `data-pg/`); a plain `docker compose up -d` is unchanged.
  - **`python -m src.migrator` sets a database up from nothing**, as the admin
    (`DATABASE_URL_ADMIN`): creates it if missing, migrates, and gives the app
    roles their logins from `WORKTIMER_APP_PASSWORD` /
    `WORKTIMER_READONLY_PASSWORD`.
  - The query editor's user SQL (Phase 3) and backups (step 8) raise a clear
    "not available on Postgres yet" message instead of failing.
  - [tests/test_smoke_pages_pg.py](../tests/test_smoke_pages_pg.py): every
    page renders on Postgres with no error logged, from the same seed data as
    the SQLite smoke test ([tests/_smoke.py](../tests/_smoke.py)).
  - Verified under compose (2026-09-28): the profile came up from an empty
    server, and a browser run on 8090 created a customer and project, ran and
    stopped a timer, added a manual entry, a task, and read them back on the
    Time Tracker and Reports — entries stored in UTC for user 1, dated by the
    local day, cost from the exact duration.
  - The login fixture restores the roles' logins after a test session, so the
    suite no longer locks out a local compose instance sharing the server.
- **Step 8, backups — decided (2026-09-28): two kinds.** The plan's in-app
  `pg_dump` would need a credential that reads every user's rows inside the
  app, undoing the roles of Phases 1 and 3, and a whole-database backup can't
  be offered to users in hosted mode anyway.
  - **In the app** ("Backup now", "Download", the palette): `backup_to`
    exports the signed-in user's data through the app role — RLS applies —
    as gzipped JSON (`worktimer-v6-export`, format 1, with the schema
    version): every user-data table, soft-deleted rows included, keys kept,
    money and hours exact as text, times in ISO 8601 with their offset, from
    one REPEATABLE READ snapshot. The Phase 4 importer will read it back. The
    backups folder lists and prunes both kinds (`.db` on SQLite).
  - **On the server**: compose's `backup` service (profile `postgres`) runs
    [scripts/pg_backup.sh](../scripts/pg_backup.sh) in the `postgres:18`
    image — a whole-database `pg_dump -Fc` as the admin, daily
    (`BACKUP_INTERVAL_SECONDS`), newest 14 kept (`BACKUP_KEEP`), in
    `./backups-pg`. The image's `pg_dump` always matches the server, so the
    app image needs no Postgres client. Restore: `pg_restore --clean
    --if-exists` as the admin (the script's header). `.gitattributes` keeps
    `*.sh` LF, since the script is mounted from a Windows checkout.
  - Verified under compose: the service wrote a dump at start that
    `pg_restore --list` reads (pg_dump 18.6 = server, owners and 0002's
    revokes included); "Backup now" and "Download" produced the export.
- **Step 5's currency, done (2026-09-28):** the customer dialog has a
  Currency field on Postgres (a `backend: postgres` field in
  `config_ui.yml`; SEK by default, any ISO code). It changes only while the
  customer has no time entries — `update_customer` refuses with "fixed once
  it has time entries", and the 0001 trigger enforces it underneath; a raise
  never changes it. Reports shows **one amount per currency** —
  `report_amounts` returns a row per currency and billing rounding runs
  within each (untagged time is one unit *per currency*), so the tile reads
  "100 NOK · 2,000 SEK", the CSV has an Amount row per currency, and the
  delta shows only for a single currency. The Time Tracker's bonus shows each
  customer's own code. On SQLite nothing changes: one currency-less row, and
  Settings' currency suffix still applies (hidden on Postgres). Tests: the
  data layer on Postgres, `report_amounts` against `report_totals` on both
  backends, the Reports page with a EUR customer; mutation-checked (untagged
  time pooled across currencies; one summed amount). Verified in a browser
  on Postgres and on SQLite.
- **Step 7, closed — nothing to build:** no page can delete a customer or
  project (disable is the only path, and the query editor is read-only since
  Phase 3); the database refuses such a delete with entries anyway.
- **Open:**
  - Step 9 (at release: SQLite is the fallback until then).
  - The Jira incremental sync's watermark is UTC now (SQLite kept Jira's own
    offset string). A Jira site in a negative-offset zone could miss a few
    hours of edits until the next full sync — check when the sync runs live.
  - The architecture guard's table list still has only the 5.x names; adding
    the v6 names needs an exception for the SQL sample text in Settings'
    query-editor skin preview.

---

## Phase 3 — Query editor lockdown

- `run_user_query` executes on the `worktimer_readonly` connection. **The role
  is the real guard**; the checks below are for good error messages.
- Reject anything but a single `SELECT` / `WITH` statement.
- `SET LOCAL statement_timeout` and a row cap.
- Default queries rewritten for the new schema, built on `v_time_entries`.
- Row edits keep working — they save through data-layer methods on the app
  role (Phase 2, step 2), never through the read-only connection.

**Status: done** (2026-09-28; SQLite keeps 5.x's editor until it leaves the
runtime).

- **A hole the plan didn't list, closed first:** row-level security keys on
  `app.user_id`, a setting any role could change with `set_config()` — from
  inside a SELECT, which the editor would now run. Migration
  [0002_lock_user_setting.sql](../migrations/0002_lock_user_setting.sql)
  revokes `set_config` (and, as a second route, UPDATE on `pg_settings`, whose
  rule calls it) from every role; the connection layer sets the user with
  `SET LOCAL` instead, which one SELECT cannot issue.
- `run_user_query` / `check_user_query` in
  [src/pg_database.py](../src/pg_database.py): one statement (a text check
  for the readable message; the server enforces it — user SQL is sent as a
  prepared statement, which can't hold two), SELECT / WITH / VALUES / TABLE
  only, on `worktimer_readonly` for the user in a **READ ONLY** transaction,
  in the user's time zone, 15 s `statement_timeout`, 5,000 rows (the page
  says when it cut). The check is `EXPLAIN` — planned, never run.
- Default queries (`time`, `customers`, `projects`, `weekly`, `monthly`)
  rewritten on `v_time_entries` and the v6 tables; `initialize_db()` adds or
  refreshes them for the user at startup. Each data layer names the tables
  its row edit opens from (`ROW_EDIT_TABLES`), so the page handles 5.x and v6
  names.
- [tests/test_pg_query_editor.py](../tests/test_pg_query_editor.py): 17 tests
  — own rows only; writes refused with a readable message, and a
  data-modifying WITH that passes the text check stopped by the database; a
  second statement refused by the server even with the text check bypassed;
  no switching users (`set_config`, `pg_settings`); timeout; row cap; local
  times; `%` in queries; the check plans without running; the defaults run
  and carry their row-edit keys. The query-editor characterisation tests run
  on both backends (two REVIEWED DIFFs: writes refused).
- **Mutation-checked:** without the `set_config` revoke 2 tests fail; without
  the `pg_settings` revoke 3; without the prepared statement 1; without the
  timeout 2; without READ ONLY 1.
- Verified under compose: the presets run; a result row opened the edit
  dialog, and saving moved the entry and re-priced it (3.5 h → 3,500); a
  `delete` and a `set_config` from the editor were refused.

---

## Phase 4 — SQLite importer

As specified in [v6_plan.md §8](v6_plan.md). Pipeline:

1. **Upload** — size-capped; authenticated in hosted mode.
2. **Normalise** a temporary copy with the old SQLite engine
   (`validate_and_migrate_schema`).
3. **Transform** — collapse SCD versions, naive local → UTC, snapshots copied
   verbatim, `git_id = 0` → `NULL`, round to öre.
4. **Load** in one transaction, into an empty account only.
5. **Report** — per customer, total hours and cost *before and after*, side by
   side. Users see their numbers match, which builds trust; any mismatch is a
   bug caught at the door.

Test corpus: a copy of your own live database; a colleague's (with
permission); a synthetic v4-era file; entries that straddle both DST changes.

**Status: built** (2026-09-28) — two corpus files still to run: a colleague's
database and a v4-era file.

- **One loader, two kinds of file.** [src/importer_v5.py](../src/importer_v5.py)
  (the legacy mapping — deletable later, as §8 asks) turns a 5.x file into the
  same shape as step 8's v6 export; `PgDatabase.import_export` loads either,
  remapping every key, in one transaction, into an empty account — or, with
  *replace*, after deleting the account's data (Phase 5's weekly re-import).
  So the app's own backups restore through the same path.
  [src/importer.py](../src/importer.py): `prepare` (read, transform, check —
  nothing written), `load`, and the before/after report per customer
  (entries, hours to 0.0001 h per entry, cost to the öre). Command line:
  `DATABASE_URL=… python -m src.importer FILE [--replace] [--dry-run]
  [--pat-key FILE]`. In the app: Settings → Data → **Import** (Postgres only;
  200 MB cap; upload authentication comes with Phase 6).
- **Transform, as §8:** the file is copied and opened with the 5.x engine,
  which normalises older files; customer versions collapse into one customer
  and one wage period per version (each ending the day before the next —
  two on one day: the later wins); snapshots copied verbatim, cost and bonus
  rounded to öre; naive local times → UTC (the repeated autumn hour's first
  occurrence; an entry that would then end before it starts ends in the
  second; the skipped spring hour read as standard time); `git_id` 0 → NULL;
  5.x's task timestamps were UTC already. Tokens the importing server can't
  read are left out, with a "re-enter them" note (`--pat-key` keeps them);
  5.x's default saved queries make way for v6's; the user's own are kept, with
  a "rewrite them" note. Entries that lost their project are kept under a
  "(no project)" project; a project name used twice for one customer is one
  project.
- **Nothing is guessed:** data v6 would refuse — a bonus period that ends
  before it starts, overlapping bonus periods, an entry that ends before it
  starts — stops the import with a list of what to fix in 5.x, including the
  SQL for 5.x's query editor.
- [tests/test_importer.py](../tests/test_importer.py): 17 tests on a 5.x file
  built with the 5.x engine — matching numbers, collapsed versions, verbatim
  snapshots, UTC and both DST changes, tasks, queries and work items, tokens
  with and without the key, refused bonus periods, empty-account rule and
  replace, a v6 export round trip into another user, lost projects, the file
  never changed, the command line.
- **Your own database** (a snapshot; no tokens decrypted): the first run
  stopped on three rows to fix in 5.x — bonus periods 3 and 8 (typo'd years)
  and **time entry 4468, which ends four days before it starts (−88.94 h on
  Random Forest / Arbete)**. It also found 5.x storing three `git_id`s as
  8-byte BLOBs, now read. With the three rows fixed in the copy, the import
  matched to the öre: six customers, 4,468 entries, 11,240.597 h and
  5,400,521.02 before and after; Castellum's three wage periods and the four
  bonus periods came through as they should.
- Verified under compose: the Settings card showed a problem file's issues
  with Import disabled, then imported a valid file and showed every customer
  matching.

---

## Phase 5 — Gate: staging and parallel run

- Deploy to the Hetzner box, **single-user**, you only.
- **Parallel run, 1–2 weeks:** keep 5.x as your daily driver; import your live
  5.x database into staging weekly and compare the importer's report. Any
  difference in totals is a bug found before anyone else's data is at stake.

**Done when:** two consecutive weekly imports match to the öre, and nothing
has been fixed in the billing path since the last one.

**Status: deployed, the weekly imports under way** (2026-09-28). Runbook:
[staging.md](staging.md).

- **Deployed 2026-09-28** to the Hetzner box: Docker from Ubuntu's packages,
  the branch in `/opt/worktimer`, passwords generated there into a root-only
  `.env`. Found on the way: `migrate` and `worktimer-pg` both built the same
  image tag, which Docker 29's containerd image store refuses when built in
  parallel — `migrate` now runs the image `worktimer-pg` builds, and the
  Postgres services have their own tag (`worktimer-app:pg`), so building them
  never replaces the SQLite app's image.
- **First import: `RESULT: match`** — every customer, and all months of the
  Reports check.
- **Access:** through the SSH tunnel already in `~/.ssh/config`
  (`localhost:18080` → the server's `127.0.0.1:8080`); nothing new listens on
  the internet.
- **Tracker tokens: opt-in** (`push_to_staging.py --with-tokens` copies 5.x's
  `.pat_key` for the import; deleted afterwards). With tokens, staging syncs
  with DevOps/Jira alongside 5.x — a stop saved with "Store to tracker" on
  posts to the real item.
- **Timers checked live on staging** (a scripted browser run, every step read
  back from Postgres): start/stop, cancel, reload / second client / app
  restart, start from a past time with a custom stop (1.5 h × 926 = 1389.00,
  bonus 138.90), re-assign on stop, delete, manual entry, two timers at once,
  the tracker-connected stop dialog — all correct.
- [scripts/staging.sh](../scripts/staging.sh) on the server (`up`, `import`,
  `gate`, `status`); [scripts/push_to_staging.py](../scripts/push_to_staging.py)
  on the PC — the weekly routine in one command: a consistent snapshot
  (SQLite backup API), copied over SSH, imported with `--replace`, the report
  kept on the server with the commit that produced it.
- **A stronger comparison than planned:** `--check-reports` also compares the
  Reports page's totals month by month — hours, cost, entries, days, each
  from its own version's report queries — so the gate proves the report
  logic, not only the stored rows. **The gate** (`staging.sh gate`): the last
  two reports both `RESULT: match`, on the same commit.
- **Dry run on your live database** (after your three 5.x fixes): every
  customer matches, and all 36 months of the Reports check match. The check
  found one more 5.x inconsistency on the way: four entries whose cached day
  (`date_key`) was a day after their start — a start edited later. The
  importer now dates entries by their start, as 5.x's Reports already did,
  and lists them (time_id 4228, 4234, 4255, 4419).

---

## Phase 6 — Online: identity and per-user state

- **Identity:** verify the Cloudflare Access JWT (signature against the team's
  public keys, audience tag); find or create the `users` row by `bk_user`
  (`sub`). Access's allow-list decides who gets in; the app provisions users on
  first login.
- **Settings switch:** multi-user mode on; blocked from turning off with more
  than one user.
- **Per-user runtime state:** `_global_tracker_engine` becomes per user;
  `AppCore` keyed by user; notes directory per user; the upload endpoints
  authenticated and scoped.
- **Sync scheduling:** per-user tracker syncs staggered, with a global
  concurrency cap.
- **Deploy:** hosted compose profile on Hetzner; Access application and policy;
  one-month sessions (see [server_setup.md](server_setup.md)).
- **Tests:** two users end to end — neither can see the other's customers,
  board, tracker items or notes.

**Status: in progress — slices 1–2 of 6 done** (2026-09-28). Started beside
the Phase 5 gate. Slice 1 is part of the gate's commit (`0699487`) and runs on
staging in single-user mode — the regression run there (the 32 timer checks,
a live tracker sync through the per-user engine) passed; later slices stay
off staging until the gate passes. An inventory of process-wide state found
more shared than the plan listed, so the work is cut into slices; **multi-user
mode must not be deployed before slice 3** — settings are still shared
between users until then.

1. **Identity, per-user data and tracker engine — done.**
   - [src/auth.py](../src/auth.py): `WORKTIMER_AUTH=cloudflare-access` (with
     `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`) turns sign-in on. The Access
     token (header, or the `CF_Authorization` cookie) is verified with PyJWT
     against the team's published keys — RS256 only, audience, issuer, expiry;
     a service token (no `sub`) is refused. No valid token: the page shows "Not
     signed in" and nothing of the app.
   - **Migration 0003:** `app_sign_in(sub, email, name)` finds or creates the
     user (email kept current), refusing `'local'`, a blank subject and a
     disabled user; `app_signed_in_users()` counts them. Both run as a role of
     their own, `worktimer_signin` — NOLOGIN, nobody's member, allowed only
     `users` — so every everyday role, the owner included, still sees no row
     without `app.user_id`. Only the app role may call them.
   - The first page of a tab resolves its user (`AppCore` is bound to it for
     the tab's life); each user has their own `PgDatabase` on one shared set of
     pools, and their own tracker engine (`get_tracker_engine(user)`), board
     column cache and init lock. The attachment endpoints and staged images
     need a sign-in and serve only the user's own.
   - **The switch is deployment config, not a Settings toggle:** a hosted
     instance must not be switchable to "no login" from inside the app. The
     block of §2 is at startup instead — a single-user process refuses a
     database people have signed in to — and multi-user mode refuses to start
     without Postgres.
   - **Found on the way:** a tracker re-init never stopped the old engine's
     hourly and 2 AM syncs, so every re-init added two more loops (single-user
     too). Fixed: the replaced engine's schedules stop.
   - Tests: the token checks (forged, expired, wrong audience or issuer,
     `alg: none` / HS256, service tokens); the sign-in functions and the role;
     pages as two simulated signed-in users (each sees only their own data; no
     token, no app); the endpoints; the single-user refusal; re-init.
     Mutation-checked: every tab acting as user 1, and staged images served
     to any signed-in user, each fail tests.
2. **Files, endpoints and logs — done.**
   - [src/user_paths.py](../src/user_paths.py): user 1 keeps `data/` as it
     was; every other user gets `data/users/<key>/`. Notes and backups (Backup
     now, its listing and pruning) live there; only user 1 adopts pre-5.1.2
     backups. External notes (files in the app's own folder) are off when
     people sign in.
   - Pasted note images: `/upload_image` needs a sign-in, takes raster images
     only (no SVG — it can carry script), 10 MB at most, into the user's
     folder. The static `/notes_assets` mount — it served the whole notes
     folder, notes and metadata included, to anyone — is now a route that
     serves only images from a note's `_assets` folder, the user's own.
   - Logs: loggers are per user (`Database.user2`, …; the Log page shows the
     plain name), each tab listens only to its user's, and the history new
     tabs replay is per user. With sign-in on, no tab listens to the root
     logger — libraries' and other users' records stay on the server console.
   - Tests: folders per user, backups per user, each user's Log page and the
     root logger, pasted images end to end as two signed-in users.
     Mutation-checked: one shared notes folder, and process-wide loggers,
     each fail tests.
3. **Settings:** what Settings writes into `config/` today — time and billing
   defaults, description templates, contacts, tags, theme, tracker defaults —
   becomes per user; `app.storage.user` keys namespaced by user.
4. **Sync scheduling:** per-user hourly and nightly syncs staggered, with a
   global concurrency cap.
5. **Deploy:** the hosted compose profile with `cloudflared`, the Access
   application and policy, one-month sessions.
6. **Two users end to end** in a real browser, then colleagues.

---

## Phase 7 — Release 6.0.0

- Compose finalised: self-host, plus the hosted profile with `cloudflared`.
- README rewritten: install is `docker compose up -d`; moving from 5.x is the
  importer; using the hosted instance needs only a browser.
- Changelog with the breaking changes: Docker required for self-hosting, saved
  queries need rewriting, PATs re-entered after import.
- Colleague onboarding: each imports their own 5.x database through
  Settings → Import on the hosted instance.
- Merge to `main`.

---

## Maybe, after 6.0.0

Not requirements — nothing is built for these; decide at the end.

- **Self-hosting on SQLite (single-user).** For installs that can't run
  Docker. This means the *v6* model on SQLite, not today's 5.x code (which
  keeps 5.x's billing rules): a SQLite version of the schema
  (`timestamptz` → UTC text, the no-overlap rules as triggers, `dates` as a
  recursive CTE, no roles or RLS), the data layer made dialect-neutral
  (local-time formatting in Python instead of `at time zone`; the few
  Postgres-only constructs rewritten) and a SQLite connection layer pinned to
  user 1. The `backends` test marker then runs the whole oracle on it.
  Estimated 1–1.5 weeks (2026-09-28), plus every later schema change written
  as two migrations. Hand-written portable SQL, not a runtime dialect
  translator (SQLGlot, SQLAlchemy): the gaps are features SQLite lacks —
  time zones, arrays, exclusion constraints, RLS — not syntax. Multi-user stays
  Postgres-only.

---

## Decisions

| Topic | Decision |
|---|---|
| Migration runner | numbered SQL files + small runner; no Alembic |
| API return shapes in the port | today's column names, aliased in SQL; stored schema fully clean |
| Release shape | one 6.0.0 on `feat/postgres-migration`, including online; Phase 5 gate before identity work |

## Progress

- [x] **0.1** Characterisation tests: billing core
- [x] **0.2** SQL behind the `Database` API
- [x] **0.3** One clock
- [ ] **0.4** Checkpoint
- [x] **1** Postgres foundation
- [ ] **2** Data layer port — in progress
- [x] **3** Query editor lockdown
- [ ] **4** SQLite importer — built; a colleague's file and a v4-era file still to run
- [ ] **5** Gate: staging + parallel run
- [ ] **6** Online — slices 1–2 of 6 (identity; files, endpoints, logs) done
- [ ] **7** Release 6.0.0

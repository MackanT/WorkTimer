# v6 implementation path

**Status:** r2 · 2026-09-27 — decisions resolved; Phase 0 in progress.
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
  `schema_migrations` table. Runs as `worktimer_owner`; applied on startup.

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

### 1.4 Connection layer

A pool plus a single `transaction(user_key)` context manager:
`BEGIN` → `SET LOCAL app.user_id` → work → `COMMIT` / `ROLLBACK`. This is the
**only** place `SET LOCAL` appears. Config: `DATABASE_URL` (app role) and
`DATABASE_URL_READONLY`; in single-user mode the user key resolves to 1.

**Done when:** an integration test writes and reads through the pool with RLS
on, and all security tests pass.

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
9. **Remove from the runtime path:** the SQLite `Database` class (kept only for
   the importer), triggers, `validate_and_migrate_schema`, the `dates` horizon
   code.

**Done when:** the full suite passes on Postgres; the characterisation diffs are
exactly the two approved ones; the app runs end to end under compose.

---

## Phase 3 — Query editor lockdown

- `run_user_query` executes on the `worktimer_readonly` connection. **The role
  is the real guard**; the checks below are for good error messages.
- Reject anything but a single `SELECT` / `WITH` statement.
- `SET LOCAL statement_timeout` and a row cap.
- Default queries rewritten for the new schema, built on `v_time_entries`.
- Row edits keep working — they save through data-layer methods on the app
  role (Phase 2, step 2), never through the read-only connection.

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

---

## Phase 5 — Gate: staging and parallel run

- Deploy to the Hetzner box, **single-user**, you only.
- **Parallel run, 1–2 weeks:** keep 5.x as your daily driver; import your live
  5.x database into staging weekly and compare the importer's report. Any
  difference in totals is a bug found before anyone else's data is at stake.

**Done when:** two consecutive weekly imports match to the öre, and nothing
has been fixed in the billing path since the last one.

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
- [ ] **1** Postgres foundation
- [ ] **2** Data layer port
- [ ] **3** Query editor lockdown
- [ ] **4** SQLite importer
- [ ] **5** Gate: staging + parallel run
- [ ] **6** Online
- [ ] **7** Release 6.0.0

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
| `pages/tasks.py` | next |

### 0.3 One clock

A small `clock` module (`now_local()`, `today_local()`), initially returning
exactly what `datetime.now()` returns today. Route the 22 `datetime.now()`
sites (7 files) that concern user time through it. The update checker's cache
timestamp can stay as it is.

No behaviour change now; in Phase 2 the switch to UTC storage with local
presentation becomes a change to one module rather than a hunt.

### 0.4 Checkpoint

Full suite green; the app smoke-tested by hand against a copy of a real 5.x
database. Phase 0 is the last point where the branch is behaviourally identical
to `main`.

---

## Phase 1 — Postgres foundation

### 1.1 Local Postgres and a test fixture

- `docker-compose.yml` gains a `postgres` service: official image, pinned
  major version, named volume, healthcheck; the app waits on
  `condition: service_healthy`.
- A `pg_db` test fixture via `testcontainers`: one container per session, a
  fresh database per test (from a template, for speed). Postgres tests are
  marked so the SQLite suite still runs without Docker during the transition.

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
  - a timer **running across a wage change** is invisible to the tracker;
    ticking it starts a second timer while the first runs on;
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
   visible (dialog dropdowns), choose it deliberately.
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
- [ ] **0.2** SQL behind the `Database` API
- [ ] **0.3** One clock
- [ ] **0.4** Checkpoint
- [ ] **1** Postgres foundation
- [ ] **2** Data layer port
- [ ] **3** Query editor lockdown
- [ ] **4** SQLite importer
- [ ] **5** Gate: staging + parallel run
- [ ] **6** Online
- [ ] **7** Release 6.0.0

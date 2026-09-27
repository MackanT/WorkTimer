# v6.0.0 build plan — Postgres, one version, two modes

**Status:** r4 · 2026-09-27 — design decisions resolved (§13). Build order:
[v6_implementation.md](v6_implementation.md). Branch: `feat/postgres-migration`.
**r4 changes:** one 6.0.0 release covering Postgres *and* online multi-user
(§12); plain numbered SQL migrations instead of Alembic.
**r3 changes:** currency lives on the customer (immutable once used);
customers/projects get `is_enabled` and no soft delete; self-hosting runs on
Docker Compose instead of embedded Postgres (§9); `v_time_entries` view for the
query editor; all §13 questions closed.
**Supersedes the open question in** [hosting_decision.md](hosting_decision.md)
(schema-per-user is no longer the chosen isolation model — see §6).

---

## 1. Goal

One codebase, one version, two deployment modes:

| | **Single-user** (self-host) | **Multi-user** (hosted) |
|---|---|---|
| Who runs it | user, on their own PC | one instance on a VPS |
| Login | none — pinned to user 1 | Cloudflare Access (SSO) |
| Runtime | Docker Compose: app + Postgres | same compose file + `cloudflared` |
| Data | one row set | isolated per user |

The switch is a setting, **not** a fork of the code.

**Users only ever need a browser.** In hosted mode the app is reachable solely
through the Cloudflare Access login; the server exposes no application port
(`cloudflared` connects outbound). SSH belongs to the administrator alone — it
is root on the whole box, every user's data and the Fernet key included.

Scope of 6.0.0: SQLite → Postgres, the data-model cleanup, `fk_user` +
row-level security, the SQLite importer, **and** online multi-user — login via
Cloudflare Access and per-user runtime state (§12).

---

## 2. The hard rule: always tenant, sometimes prompt

The isolation machinery is **always on**. Single-user mode pins
`app.user_id = 1` and skips rendering the login screen. We never build a switch
that decides *whether the tenancy filter applies* — "auth optional"
implemented as "sometimes we skip the WHERE clause" is how leaks happen.

- A `users` table exists in both modes. Single-user self-hosters have one row.
- Every user-data table carries `fk_user` from 6.0.0 onward, even before login
  exists — touching every table twice is the expensive mistake to avoid.
- Turning multi-user **on** is trivial (existing rows belong to user 1).
  Turning it **off** with several users' data present is ambiguous — **block
  it** in the settings UI.
- Identity in hosted mode comes from the Cloudflare Access JWT. `users.bk_user`
  stores the identity provider's stable **subject** (`sub` claim), not the
  email — emails change. Single-user mode uses `bk_user = 'local'`.
- The app stores **no passwords** and needs no reset flow or session store.

---

## 3. The customer model today — and the billing invariants

Read this before touching the schema.

### What the code does

`customers` is a hybrid SCD. What each operation actually does today:

| Operation | Function | Effect |
|---|---|---|
| Wage change | `insert_customer` (existing name) | closes the current row (`is_current = 0`, `valid_to` = day before), inserts a new row with a **new `customer_id`**, then **re-points every project** to the new id. Time entries are **not** re-pointed. |
| Rename / colour / tracker | `update_customer` | overwrites **every version row** (`where customer_name = ?`), and renames the cached name on every `time` row |
| Disable | `disable_customer` | `is_current = 0` on **every version** |
| Enable | `enable_customer` | `is_current = 1` on the latest version, found via `valid_to is null` |

So `time.customer_id` is a genuine point-in-time reference to the version
current when the entry was logged.

### The invariant that must survive

The insert trigger copies `wage` (from the customer version) and `bonus` (from
`bonus`, by the entry's date) onto each `time` row, and the update trigger
derives:

```
total_time = (julianday(end_time) - julianday(start_time)) * 24
cost       = wage * total_time
user_bonus = bonus * wage * total_time
```

**Those copies are point-in-time snapshots.** A wage change must never
retroactively alter last year's invoices. They stay, renamed to say what they
are (§5).

### Three problems with the current shape

1. **`is_current` means two things** — "latest version" *and* "not disabled".
   For a disabled customer no row has `is_current = 1`, which is why
   `enable_customer` must find the latest version through `valid_to is null`.
2. **Two paths to a customer disagree.** After a wage change, an old time entry
   reaches `time.customer_id` → the *old* version, but
   `time.project_id → projects.customer_id` → the *new* version. Any report or
   saved query joining through the project silently gets today's wage.
3. **Type 1 and Type 2 attributes share one table.** Wage is versioned; name,
   colour and tracker are overwritten on every version — so every edit touches
   many rows, and projects must be re-pointed on each wage change.

### Resolution: split entity from wage history

- **`customers`** — one row per customer: name, colour, tracker, currency,
  `is_enabled`. A rename is one row; disable is one flag. This is also the
  `is_enabled` flag that replaces the "not disabled" half of `is_current`.
- **`customer_wages`** — Type 2 history: `wage`, `valid_from`, `valid_to`. A
  wage change appends a row; nothing else moves. "Latest version" is simply
  `valid_to is null`.
- Projects and time entries reference the **stable** `customers.key_customer`.
  No re-pointing, ever.
- Time entries do not reference a *version*: they snapshot wage and bonus, and
  **the snapshot is the historical record**.
- **Both wage and bonus are looked up by the entry's date.** Today wage comes
  from the version the entry was created against while bonus goes by date;
  that never mattered while entries were logged live, but back-dating entries
  is now possible, so both must follow the date. Pin the old behaviour in
  characterisation tests before changing it (§11).

---

## 4. Conventions

### Keys

| Prefix | Meaning | Example |
|---|---|---|
| `key_{entity}` | primary key (surrogate) | `customers.key_customer` |
| `fk_{entity}` | reference to another table's `key_` | `time_entries.fk_project` |
| `fk_{role}_{entity}` | reference where the role matters, incl. self-reference | `tasks.fk_parent_task` |
| `bk_{entity}` | business key — identity from **outside** this database | `work_items.bk_work_item` (tracker's id), `users.bk_user` (IdP subject) |

Rules:
- `{entity}` is **singular**: `key_customer`, `fk_project`.
- The prefixes are reserved. **No column ends in `_id` or `_key`**, and no
  other column starts with `key_` / `fk_` / `bk_`.
- `bk_` exists only where an identity lives outside the app. App-native
  entities (customers, projects, tasks) are identified by `key_` alone; their
  names are unique attributes, not business keys.
- A column holding *another* table's business key keeps the `bk_` name, which
  makes the join self-describing: `time_entries.bk_work_item` joins
  `work_items.bk_work_item`. It is not an `fk_` because work items are a
  re-syncable cache whose surrogate keys are not stable.
- **Exemption:** the audit columns keep their conventional names,
  `created_by` / `updated_by`.
- Sentinels become `NULL`: `git_id = 0` meaning "none" → `bk_work_item is null`.

Tables: `snake_case`, plural. `time` → `time_entries`, `bonus` → `bonuses`,
`queries` → `saved_queries`, `devops` → **`work_items`** (it has held Jira
issues since 5.1.0). Reporting views take a `v_` prefix; `dates` keeps its
name because it replaces a table. Booleans read as predicates: `is_enabled`,
`is_done`, `is_completed`.

### Types and money

- All timestamps `timestamptz`, **stored UTC**. Calendar dates `date`. No dates
  in `text`. Booleans are `boolean`, never `integer`.
- **`wage`: `integer`** — always whole units per hour. (If a fractional rate
  ever appears, `alter column type numeric(10,2)` is a one-line migration.)
- **`duration_hours`: `numeric(10,4)`** — **not** rounded. Rounding the
  duration before multiplying compounds (at 1,000 SEK/h a 0.01 h step is up to
  ±5 SEK per entry), and a rounded duration cannot be recovered.
- **`cost`, `user_bonus`: `numeric(12,2)`** — computed from the exact duration,
  **rounded once**, to öre. Always recomputable from the duration if more
  precision is ever wanted.
- **`bonus_pct`: `numeric(5,4)`**.

### Currency

- **`customers.currency char(3) not null default 'SEK'`** (ISO 4217).
- A customer's currency never changes — that is the business rule, so it lives
  on the customer and time entries need no currency snapshot; it is reached
  through `fk_project → customers`.
- **Enforce the rule:** currency is editable only while the customer has no
  time entries. The model relies on it being immutable; a mis-click after
  entries exist would re-denominate history.
- **Reports aggregate per currency.** Summing SEK and EUR is meaningless, so
  "total earned" becomes one total per currency. No FX conversion.

### Standard metadata

| Column | Type | Notes |
|---|---|---|
| `fk_user` | `int not null` | tenancy; default from session (§6) |
| `created_at` | `timestamptz not null default now()` | |
| `updated_at` | `timestamptz not null default now()` | maintained on write |
| `created_by` | `int` | → `users.key_user` |
| `updated_by` | `int` | → `users.key_user` |
| `deleted_at` | `timestamptz null` | soft delete, where it applies |

Cache tables (`work_items`) carry `synced_at` instead of the audit set.

### Timezone policy

Everything is stored and computed in UTC; local time is **presentation only**,
driven by `users.timezone`. This retires the ~22 `datetime.now()` sites that
assume server clock = user clock.

**One deliberate exception:** each time entry stores its **local date**
(`fk_date`) at logging time. Deriving it from UTC `started_at` puts an entry
begun at 00:30 Stockholm time (22:30 UTC in summer) on the *previous* day in
every daily and weekly report. Storing it also keeps historical entries on
their day if a user later changes timezone.

### Disable and delete

Customers and projects are never soft-deleted — for them, "disabled" is the
only state that matters, so there is one flag rather than two.

| Table | Mechanism | Rule |
|---|---|---|
| `customers`, `projects` | `is_enabled` | Disable hides from pickers and the timer. **Never cascades** — projects are hidden *through the join*, each keeping its own flag, so re-enabling a customer restores exactly the projects that were enabled. Time entries are never touched; totals are always complete. |
| `customers`, `projects` | hard delete | **Only when nothing references them** — e.g. created by mistake. Enforced by the database (`on delete restrict`); the UI turns the refusal into "has N time entries — disable instead". |
| `time_entries`, `tasks`, `saved_queries`, `bonuses` | `deleted_at` | Soft delete of an explicit, individual row. |
| `work_items` | hard delete | Cache. `on delete cascade` from its customer. |
| `trackers` | hard delete | Credentials — delete must mean gone. Linked customers are detached (`on delete set null`), as today. |

- Disabled customers and projects keep their names: re-enable rather than
  re-create, so plain unique constraints suffice. Partial unique indexes
  (`... where deleted_at is null`) are needed only on soft-deleted tables.
- **Every aggregate excludes soft-deleted rows.** A deleted entry in
  `sum(duration_hours)` is a wrong invoice, not a visual glitch.
- A real purge path is required eventually (GDPR erasure), behind proper UI.

---

## 5. Target schema

**`users`** — `key_user`, `bk_user` (IdP subject; `'local'` in single-user),
`email`, `display_name`, `timezone` (IANA, default `Europe/Stockholm`),
`is_enabled`, `created_at`, `updated_at`.

**`customers`** — entity, Type 1
- `key_customer`, `fk_user`
- `customer_name` — unique per user
- `currency char(3) default 'SEK'` — immutable once time entries exist
- `color`, `fk_tracker` (`on delete set null`), `tracker_project`,
  `expected_work_pct`, `sort_order`
- `is_enabled`, metadata — **no** `deleted_at`
- dropped: `integration_type` (redundant with the linked tracker's type),
  `start_date` (= the first wage row's `valid_from`)

**`customer_wages`** — Type 2 history
- `key_customer_wage`, `fk_user`, `fk_customer`
- `wage integer`, `valid_from date not null`, `valid_to date` (null = current)
- **No overlaps, enforced by the database:**
  `exclude using gist (fk_customer with =, daterange(valid_from, valid_to) with &&)`
  (needs the `btree_gist` extension, bundled with the official Postgres image)
- metadata. Corrections are edits; historical cost is safe because entries
  snapshot.

**`projects`**
- `key_project`, `fk_user`, `fk_customer` — stable, never re-pointed
- `project_name` — unique per customer
- `bk_work_item` (was `git_id`, the default work item; `NULL` = none)
- `is_enabled` (was `is_current`), `sort_order`, metadata — **no**
  `deleted_at`

**`time_entries`** (was `time`)
- `key_time_entry`, `fk_user`, `fk_project` (`on delete restrict`)
- `started_at`, `ended_at` (`timestamptz`, UTC)
- `fk_date` — local date as `YYYYMMDD` (§4); logical reference to the `dates`
  view, not an enforced FK
- `duration_hours numeric(10,4)`
- `wage_snapshot integer`, `bonus_pct_snapshot numeric(5,4)` — both looked up
  by the entry's date
- `cost numeric(12,2)`, `user_bonus numeric(12,2)`
- `bk_work_item` (was `git_id`), `comment`
- metadata, `deleted_at`
- dropped: `customer_name`, `project_name` (caches), `fk_customer` (derived
  through `fk_project`, so the two can never disagree). Names come back via
  `v_time_entries` (§7).

**`bonuses`** (was `bonus`) — `key_bonus`, `fk_user`, `bonus_pct numeric(5,4)`,
`valid_from date`, `valid_to date`, same no-overlap exclusion constraint,
metadata, `deleted_at`.

**`dates`** — a **view** over `generate_series`, not a table:
`key_date` (`YYYYMMDD`), `date`, `year`, `iso_year`, `month`, `week` (ISO),
`day`. No horizon to maintain — the extension logic in `initialize_db()` is
deleted. `week` is already ISO today (`isocalendar().week`) and Postgres'
`extract(week)` is ISO too, so values match. `iso_year` is new: grouping by
calendar `year` + ISO `week` splits ISO week 1 across two years at New Year.

**`work_items`** (was `devops`) — cache, hard delete
- `key_work_item`, `fk_user`, `fk_customer` (was `customer_name`;
  `on delete cascade`)
- `bk_work_item` (the tracker's id; unique on `(fk_customer, bk_work_item)`)
- `bk_parent_work_item` (was `parent_id`), `display_ref` (e.g. `PROJ-123`)
- `item_type`, `title`, `state`, `board_column`, `is_done` (was
  `board_column_done`), `assigned_to`, `changed_at` (`timestamptz`, was text),
  `priority`, `description_text`, `synced_at`

**`tasks`**
- `key_task`, `fk_user`, `fk_customer`, `fk_project` (replacing the name
  columns — the reason the original FKs were dropped), `fk_parent_task`
- `title`, `description`, `status`, `priority`, `is_completed`, `assigned_to`,
  `due_date`, `estimated_hours`, `actual_hours`, `progress_pct`, `tags`,
  `completed_at`
- metadata (`created_by` / `updated_by` become user references — text today),
  `deleted_at`

**`trackers`** — credentials, hard delete
- `key_tracker`, `fk_user`, `tracker_name` (unique per user),
  `integration_type`, `org_url`, `pat_token` (Fernet, `enc:` prefix),
  `token_expires`, metadata

**`saved_queries`** (was `queries`) — `key_saved_query`, `fk_user`,
`query_name` (unique per user among non-deleted), `query_sql`, `is_default`,
metadata, `deleted_at`.

---

## 6. Isolation: `fk_user` + row-level security

Chosen over schema-per-user. The original argument for schemas was query-editor
safety; §7 removes that, and RLS wins on everything else: one migration instead
of N, no runtime DDL, correct behaviour under transaction pooling.

Per table:

```sql
alter table time_entries add column fk_user int not null
    default nullif(current_setting('app.user_id', true), '')::int;
alter table time_entries enable row level security;
alter table time_entries force row level security;   -- owner included
create policy tenant on time_entries using (
    fk_user = nullif(current_setting('app.user_id', true), '')::int
);
```

- The app issues **`SET LOCAL app.user_id = '<key_user>'`** at the start of
  every transaction. `SET LOCAL` is transaction-scoped, so it is correct under
  pgbouncer transaction mode — unlike `SET search_path`, which silently leaks
  between users.
- **This lives in exactly one place** in the connection layer, never at call
  sites. `SET LOCAL` outside an explicit transaction silently does nothing.
- Unset session variable → policy compares against NULL → no rows. **Fails
  closed.**
- The column `DEFAULT` means inserts need no tenancy edit.
- **Every unique constraint includes `fk_user`.**

| Role | Used by | Notes |
|---|---|---|
| `worktimer_owner` | the migration runner | owns the tables |
| `worktimer_app` | the app | **no `BYPASSRLS`** |
| `worktimer_readonly` | query editor | `select` only, RLS applies |

Keys become globally unique across users, so per-user sequences show gaps.
Cosmetic; say so anywhere the UI shows a key.

---

## 7. Query editor

Keep the feature, remove the danger:

- connect as `worktimer_readonly` — writes are impossible
- reject anything but a single `SELECT` / `WITH` statement
- `statement_timeout` and a row cap
- RLS means a user sees only their own rows, whatever they write

**`v_time_entries`** — time entries with customer name, project name and
currency joined back in, soft-deleted rows excluded. Everyday queries need no
joins, which matters now that the name columns are gone from the table. The
default **"time"** query is rewritten on top of it, so it still shows at a
glance which customer and project each entry belongs to. Created
`with (security_invoker = true)`, so RLS is evaluated as the querying role
rather than the view's owner.

Users' own saved queries are SQLite dialect with old table and column names;
they will break. The defaults get rewritten; users get a changelog heads-up.

---

## 8. SQLite import (Settings)

Required — without it no existing user migrates.

- Upload `worktimer.db` through the UI; parsed server-side with stdlib
  `sqlite3`.
- **Let the old code normalise old files.** Open the upload with the
  *existing* SQLite `Database` class and run `validate_and_migrate_schema()`
  first, so a v4-era file is brought to the known 5.x shape by code that
  already works.
- **Collapse the SCD versions.** All `customers` rows sharing a name become one
  `customers` row (`currency = 'SEK'`) plus one `customer_wages` row per
  version. Every old `customer_id` — any version — maps to the single new
  `key_customer`.
- **Copy snapshots verbatim; never recompute.** `wage` → `wage_snapshot`,
  `bonus` → `bonus_pct_snapshot`. Historical cost must survive exactly.
  `cost` / `user_bonus` are rounded to öre on import, consistent with §4 (a
  change of < 0.005 per row).
- **Timestamps are naive local times** in old files (`datetime('now',
  'localtime')`). Attach the user's timezone, convert to UTC, and take
  `fk_date` from the local date. The repeated hour at the autumn DST change is
  ambiguous — take the first occurrence.
- `git_id = 0` → `NULL`.
- **PATs will be unreadable.** `.pat_key` is deliberately excluded from backups,
  so uploaded files carry `enc:` tokens with no key. Detect it and reuse the
  "re-enter them" message from `pat_crypto.py`.
- **Import only into an empty account**, or require explicit "replace
  everything". No natural key exists to dedupe entries on.
- Keep the legacy→new mapping in **one module**, deletable once everyone has
  migrated.
- The endpoint is authenticated and size-capped. The existing upload endpoints
  are neither ([AUDIT.md:156](../AUDIT.md#L156)).

---

## 9. Deployment: Docker Compose for both modes

One artifact. The repo already ships a `Dockerfile` and `docker-compose.yml`
and the app already detects Docker (`WORKTIMER_DOCKER`), so this extends an
existing, supported path rather than adding a new one.

- **Self-host:** `docker compose up -d` → app + Postgres.
- **Hosted:** the same file plus a `cloudflared` service (compose profile or
  override file); the app publishes **no** port — `cloudflared` reaches it over
  the compose network.
- **The app only knows a connection string**, so anyone who already runs
  Postgres can point at it instead.
- Postgres data lives in a **named volume**, never a bind mount into a OneDrive
  folder — `pyproject.toml` already records OneDrive sync causing "Access is
  denied", and a Postgres data directory synced mid-write *corrupts*.
- **Fix while here:** today's compose publishes `"8080:8080"`, i.e. on every
  interface, so a Docker self-host exposes the unauthenticated app to the whole
  LAN — despite `main.py`'s localhost-by-default intent. Self-host publishes
  `"127.0.0.1:8080:8080"`.
- **Backups:** the in-app backup calls `pg_dump`, so the app image installs
  `postgresql-client` matching the server's major version.

**The trade-off, accepted:** the self-host floor rises from "Python" to
"Docker" — on Windows that means WSL2 and admin rights once. That is acceptable
*because* a hosted version now exists: anyone who finds setup a hassle uses
hosted. Docker Desktop needs a paid licence at companies over 250 employees or
$10M revenue; **Rancher Desktop** and **Podman Desktop** are free alternatives
that run the same compose file.

The test suite's Postgres fixture uses a throwaway container (e.g.
`testcontainers`), so running tests needs Docker too.

---

## 10. Port inventory

| Area | Work |
|---|---|
| Dialect | 37× `strftime`, 14× `julianday`, 82× `date(`, `datetime('now','localtime')` → `extract(epoch …)`, `to_char`, `now()`. Runs through billing math. |
| Triggers (3) | Delete. `duration_hours` / `cost` / `user_bonus` and the snapshot lookups move into **one Python write path**. |
| Customer versioning | `insert_customer`'s close-and-re-point logic is replaced by appending a `customer_wages` row. |
| `dates` | Table + horizon extension in `initialize_db()` → one view. |
| Migrations | `validate_and_migrate_schema` is SQLite-catalog-based (7× `pragma`, 15× `sqlite_master`). Replaced by **numbered SQL files** (`migrations/NNNN_name.sql`) applied by a small runner, each in a transaction, tracked in `schema_migrations`. Not Alembic: with no ORM it would add SQLAlchemy purely as a runner. The old engine survives only inside the importer (§8). |
| Connection layer | `database.py` (~2,570 lines), one locked `sqlite3` connection → psycopg pool; `backup_to` → `pg_dump`. |
| SQL locations | ~74 statements in `database.py`, ~35 in `globals.py`, `root.py`, `time_tracking.py`, `command_palette.py`, `query_editor.py`. **Consolidate into the data layer.** |
| Dropped-column readers | Anything reading `customers.integration_type`, `customers.start_date`, or `time.customer_id` / `customer_name` / `project_name` moves to the tracker, the first wage row, or a join. |
| Tests | 6 files use `sqlite3` directly → Postgres test container. |

---

## 11. Testing strategy

**Characterisation tests first, before any port work.** Pin the current
SQLite behaviour as golden values; the port's definition of done is "these
same numbers come out of Postgres" — with deliberate, reviewed changes only
where this plan changes the rules (rounding to öre, wage lookup by date).

- **Assert on public-function outputs, never on SQL text or column names** —
  otherwise the renames break every test and prove nothing.
- Golden values for `total_time`, `cost`, `user_bonus`, and report aggregates.
- **Invariant:** changing a customer's wage does not alter historical cost.
  Enforced today only by trigger behaviour and documented nowhere.
- **Wage lookup:** pin today's "version at creation" behaviour, then change it
  to "by entry date" as a reviewed diff.
- **Week numbering** around New Year, and **local-date assignment** for entries
  near midnight.
- **Rounding:** cost from exact duration, rounded once.

Baseline: ~250 tests across 32 files; billing math is touched in
`test_database.py`, `test_reports.py`, `test_time_reassign.py`,
`test_tracker_split.py`, `test_trackers.py`.

---

## 12. Release sequencing

**One release, 6.0.0**, built on one long-lived branch,
`feat/postgres-migration`. Self-host SQLite → self-host Postgres is invisible
to end users and does not justify a major version on its own; the release that
matters to them is the one where they can open a URL and log in.

It contains, in build order (details in
[v6_implementation.md](v6_implementation.md)):

1. **Schema pass** — Postgres on Docker Compose, the §3–§5 model, `fk_user` +
   RLS, disable/delete semantics, query-editor lockdown, SQLite importer. From
   the user's seat: no login, same numbers (to the öre), new plumbing.
2. **Gate: single-user staging and parallel run** on real data. Billing
   numbers must be proven on the new schema *before* multi-user is layered on
   top — this preserves the part of the old "never port and add auth at once"
   rule that actually mattered: when a number is wrong, there is only one
   possible cause.
3. **Identity** — login via the Access header, the settings switch, per-user
   `_global_tracker_engine` (today a process-wide singleton —
   [app.py:22](../src/core/app.py#L22) — so on a shared instance one user's
   tracker connections would serve everyone), and sync scheduling across users
   (ten users' hourly and 2 AM syncs in one event loop need staggering and a
   concurrency cap). App code only, no migrations.

Long-lived-branch hygiene: merge `main` into the branch whenever a 5.1.x fix
lands there, and keep the suite green at every commit.

---

## 13. Decisions

All design questions are closed.

| Topic | Decision | Round |
|---|---|---|
| Isolation | `fk_user` + RLS, always on; single-user pins user 1 | r1 |
| Key naming | `key_` / `bk_` / `fk_`; singular entity; audit columns exempt; views `v_` | r1–r2 |
| Money | `wage` integer; duration unrounded; `cost` / `user_bonus` `numeric(12,2)`, rounded once | r1–r2 |
| Currency | on the customer, default SEK, immutable once entries exist; reports per currency, no FX | r2 |
| Customer model | split into `customers` + `customer_wages` | r2 |
| Wage and bonus lookup | by the entry's date (back-dated entries are now possible) | r2 |
| Disable / delete | customers & projects: `is_enabled` + hard delete only when unreferenced; soft delete elsewhere; nothing cascades | r2 |
| Local date | stored on each entry at logging time | r2 |
| `dates` | `generate_series` view | r1 |
| Column drops | `customers.integration_type`, `customers.start_date`, `time_entries.fk_customer`; names return via `v_time_entries` | r2 |
| Self-hosting | Docker Compose (same artifact as hosted) | r2 |
| Hosted access | own domain, DNS on Cloudflare; Cloudflare Access (free ≤ 50 users) — see [server_setup.md](server_setup.md) | r2 |
| Migrations | numbered SQL files + a small runner; no Alembic | r4 |
| Release shape | one 6.0.0 (Postgres + online) on one long-lived branch, with a single-user parallel-run gate before identity work | r4 |

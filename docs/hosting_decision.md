# Decision record: self-hosted SQLite vs hosted service on Postgres

**Status:** OPEN — consciously deferred (2026-09-01)
**Context at time of writing:** WorkTimer v5.0.4 · 4 self-hosting users, a 5th expected · single-user architecture

---

## The choice

1. **Stay self-hosted (SQLite)** — the current model. Each user runs the app
   locally (`python main.py`); SQLite is fully adequate for a single writer.
   No work required.
2. **Become a hosted service (Postgres)** — one deployment on a VPS/cloud,
   in-app login, each user's data isolated in their **own Postgres schema**.
   Target scale is ~1–20 users.

A full multi-tenant SaaS (shared tables + `tenant_id`, hundreds/thousands of
users, billing, horizontal scaling) was considered and **explicitly ruled out**
as overkill for the project's ambitions.

## Why this is a real fork (what the current code assumes)

The architecture equates *the process* with *the user*:

| Assumption | Where |
|---|---|
| No identity — every visitor to the port is the owner | no login anywhere; `main.py` binds localhost by design |
| One shared SQLite for all connections | `_shared_databases` in `src/globals.py` (keyed by DB file path) |
| Arbitrary SQL as a feature | the query editor runs raw SQL against the whole DB |
| Secrets as plaintext rows | `customers.pat_token`; `/devops_attachment` proxies with them, unauthenticated |
| Server clock = user clock | ~22 sites using `datetime.now()` / SQL `localtime`; `date_key`, triggers, MTD logic |

Plus unauthenticated endpoints (`/upload_devops_image`, `/upload_image`,
`/devops_attachment`), per-install filesystem state (notes, backups,
`.storage_secret`), and NiceGUI holding per-client UI state in server memory.

## Option 1 — stay self-hosted

- **Pros:** zero work; zero-dependency install (stdlib SQLite); single file =
  trivial backup; the query editor is inherently safe (your DB is yours);
  battle-tested as-is.
- **Cons:** every user must install/update themselves (N × `git pull` per
  release); onboarding each new user costs support time; no access from
  machines without the install; PATs sit on every user's disk.
- **Note:** *concurrency is NOT a reason to leave SQLite* — with one file per
  user there is exactly one writer per DB, identical to today's workload. The
  "SQLite isn't for multi-user" concern only applies to a shared database.

### Interim hosted variants that need (almost) no code
- **One instance behind an auth proxy** (Caddy/Traefik + Authelia / basic auth /
  Tailscale): ~a day of ops, but all users of that instance share one dataset.
- **Container-per-user** (own container + SQLite volume + subdomain each):
  physical data isolation, full feature set retained, ~1–3 weeks of ops for a
  fleet; ~200–300 MB RAM per user. Scales to dozens, not thousands.

## Option 2 — hosted on Postgres, schema-per-user

- **Pros:** one deployment to update (release once, everyone current); real
  login with per-user privacy; central backup/monitoring/admin; kills the
  file-locking class of problems (OneDrive!); the natural base if the user
  count keeps growing; PG is home turf operationally.
- **Cons:** the largest refactor in the project's history (see sizing);
  self-hosting floor rises (see below); PG dialect breaks users' saved queries;
  ops responsibility for everyone's data (PATs of all users on one box —
  encrypt at rest becomes mandatory, endpoints need session auth).

### Key design decision (already made): schema-per-user, not tenant_id
Postgres **schema-per-user** (`SET search_path = user_x`) is the direct analog
of what makes the current code cheap to isolate — `_shared_databases` is keyed
by DB *path* today; re-key by *schema* and:
- the ~200 hand-written queries stay untouched (no `tenant_id` in every WHERE),
- the query editor stays safe (a user's connection sees only their schema),
- per-user export/backup stays trivial (`pg_dump --schema`).

### Port inventory (measured 2026-09-01)
| Area | Surface |
|---|---|
| Duration/date math | 7× `julianday`, 35× `strftime`, `datetime('now','localtime')` → `extract(epoch …)`, `to_char`, `now()`; runs through **billing math** |
| Triggers (4) | SQLite syntax → better plan: move `total_time`/`cost` computation into Python on write and delete the trigger machinery |
| Schema auto-migration | 7× `pragma`, 15× `sqlite_master` — the whole `validate_and_migrate_schema` engine is SQLite-catalog-based → rewrite on `information_schema` or adopt Alembic |
| Connection layer | `database.py` (~2000 lines), single locked connection → psycopg pool; `backup_to` → `pg_dump` |
| Query editor + saved queries | presets and users' saved queries are SQLite dialect → one-time rewrite + user heads-up |
| Tests | 5 files use `sqlite3` directly; suite needs a PG test instance |
| Existing users | need a **SQLite → PG migration tool** (dump each user's `worktimer.db` into their schema) |

**Sizing: ~2–4 weeks focused.** Mechanical but wide — every edit runs through
billing math or a user-facing SQL surface, so each needs verification.

### Sequencing rules (agreed)
1. Do the PG port as its **own behavior-identical release** (5.1.0: same
   single-user app, PG underneath, full test suite green) **before** adding
   auth/tenancy (5.2). Never both at once.
2. **No dual SQLite/PG backend.** Triggers, catalog introspection, and the
   user-facing SQL dialect can't be abstracted cheaply; a fallback nobody needs
   would tax every future change. Pick PG, delete SQLite.

### Self-hosting under option 2 (it survives, with a higher floor)
Friction ladder for a Windows self-hoster:
Windows PG installer < WSL < Docker compose (app+PG, one command) <
**embedded Postgres via a pip package (e.g. `pgserver`)** — the app owns a
portable PG child process in a data dir: no install, no admin rights, self-host
UX ≈ today's. Hosted vs self-hosted then differ by one connection string.
Caveats: ~50 MB binaries, platform wheels, younger dependency than stdlib SQLite.

## Decision triggers — what would flip this to option 2

- Onboarding/supporting self-hosted installs (N × git pull per release, install
  help) starts costing real time; watch this around **~8–10 users**.
- A prospective user can't/won't self-host at all.
- A second device / access-from-anywhere need appears among existing users.

**Asymmetry that justifies waiting:** 1 → 2 is a clean upgrade later (all
features carry over; the port doesn't get bigger with time). 2 → 1 would never
happen. Staying on 1 until demand is real costs nothing but the eventual port.

## Do-regardless item

Before *any* hosted variant (even the no-code proxy ones): encrypt `pat_token`
at rest (symmetric key from the environment). Self-hosted plaintext PATs are
the owner's risk; hosted plaintext PATs are every user's risk on one box.

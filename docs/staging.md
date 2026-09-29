# Staging — the Phase 5 gate

**What it is:** the Postgres WorkTimer on the Hetzner box ([server_setup.md](server_setup.md)),
**single-user, you only**, while 5.x stays your daily driver. Every week your
live 5.x database is imported into it and the numbers compared. Phase 5 is done
when **two consecutive weekly imports match — to the öre, per customer and per
month — on the same code** ([v6_implementation.md](v6_implementation.md), Phase 5).

> **No secrets in this file** (the repo is public). Passwords are generated on
> the server and live only in its `/opt/worktimer/.env`.

- **Reached only through your SSH tunnel.** The app binds to the server's
  localhost; nothing new listens on the internet. Login (Cloudflare Access)
  comes with Phase 6. Your `~/.ssh/config` already forwards
  `localhost:18080` → the server's `127.0.0.1:8080`, so staging uses port 8080
  there: **http://localhost:18080** while `ssh worktimer` is open.
- **Tracker tokens: opt-in.** A plain weekly import leaves them out (no Board,
  no sync). `--with-tokens` brings them along, re-encrypted with staging's own
  key (`data-pg/.pat_key`). Staging then syncs with DevOps and Jira alongside
  5.x — reading is harmless, but a card moved or an item edited on staging
  changes the real one.
- **Backups:** the `backup` service dumps the whole database daily into
  `/opt/worktimer/backups-pg` (newest 14) — `scripts/pg_backup.sh`.

---

## Once: set the server up

As root on the server (`ssh worktimer`):

```bash
# Docker from Ubuntu's own packages (patched by unattended-upgrades)
apt-get update && apt-get install -y docker.io docker-compose-v2 docker-buildx

# The code: this branch, read-only from GitHub
git clone --branch feat/postgres-migration https://github.com/MackanT/WorkTimer.git /opt/worktimer
cd /opt/worktimer

# Secrets, generated here and never shown (root-only file)
umask 077
cat > .env <<EOF
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
WORKTIMER_APP_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
WORKTIMER_READONLY_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
PG_APP_PORT=8080
EOF

scripts/staging.sh up       # build, migrate, start app + backups
```

Then, on your PC: `ssh worktimer` (keeps the tunnel open) and browse
**http://localhost:18080** — an empty WorkTimer until the first import.

Recommended in the Hetzner console: a **Cloud Firewall** allowing inbound
port 22 only (the server listens on nothing else anyway).

## Every week: import and compare

On your PC, from the WorkTimer checkout, with 5.x running as usual:

```powershell
uv run python scripts/push_to_staging.py --with-tokens   # or without, for no tokens
```

It takes a consistent snapshot of `data/worktimer.db` (SQLite's backup API —
safe while 5.x runs), copies it (and with `--with-tokens`, 5.x's
`data/.pat_key`) to the server, and runs `scripts/staging.sh import` there:
the importer replaces staging's data with the snapshot, deletes the copies,
restarts the app (reload the browser) and prints

- per customer: entries, hours and cost, 5.x and v6 side by side;
- per month (`--check-reports`): the Reports page's hours, cost, entries and
  days, computed by each version's own report queries;
- a last line `RESULT: match` (exit 0) or `RESULT: MISMATCH` (exit 3).
  A file problem (data v6 refuses) stops before anything is replaced, with
  the SQL to fix it in 5.x.

Each report is kept on the server in `/opt/worktimer/staging-reports/`, with
the commit that produced it. The snapshot is deleted once imported.

**The gate:**

```bash
ssh worktimer /opt/worktimer/scripts/staging.sh gate
```

passes when the last two reports both say `match` and name the same commit.
A mismatch is a bug to fix before going further; a fix in the billing path
restarts the count (the next two imports must match on the new code).

## Other commands

| | |
|---|---|
| `scripts/staging.sh status` | containers, whether official, and the latest reports' results |
| `scripts/staging.sh up` | update: pull this branch, rebuild, restart — the data, settings and saved preferences stay |
| `scripts/staging.sh official` | make this the official WorkTimer (below); imports are refused from then on |
| `docker compose --profile postgres logs -f worktimer-pg` | the app's log |
| `docker compose --profile postgres run --rm backup pg_restore --list /backups/<file>` | inspect a backup |

## Backups

**On the server:** the `backup` service dumps the whole database into
`/opt/worktimer/backups-pg` once a day (the newest 14 kept) —
[scripts/pg_backup.sh](../scripts/pg_backup.sh).

**Off the server** — the server is the only live copy, so its backups must
not live only on it:

- **Hetzner Backups:** in the Hetzner console, the server → *Backups* → enable.
  Seven daily snapshots of the whole server, about 20 % of its price.
- **Copies on your PC:** from the WorkTimer checkout,

  ```powershell
  uv run python scripts/pull_backups.py --to "C:\Users\<you>\OneDrive\WorkTimer-backups"
  ```

  copies each dump not already there (the newest 30 kept; a OneDrive folder
  adds a cloud copy). To run it daily: Task Scheduler → *Create Basic Task* →
  daily, some time after lunch (the dump is written around midday) → *Start a
  program*: `uv`, arguments `run python scripts\pull_backups.py --to "<that
  folder>"`, *Start in*: the checkout folder.

**Restore** (as the admin; the app stopped so nothing writes meanwhile), on
the server in `/opt/worktimer`:

```bash
docker compose --profile postgres stop worktimer-pg
docker compose --profile postgres run --rm backup \
  pg_restore --clean --if-exists -d worktimer /backups/worktimer_<stamp>.dump
docker compose --profile postgres start worktimer-pg
```

From a copy on your PC (the server lost): set a new server up as above
(`staging.sh up`), `scp` the dump into its `/opt/worktimer/backups-pg/`, then
restore the same way. Checked 2026-09-29: a dump restored into a scratch
database held every entry, customer, work item, tracker token and security
rule of the live one at dump time.

## Making it the official WorkTimer

When the server is to become your daily WorkTimer — reached from any PC
through its SSH tunnel — the parallel run ends. Once:

1. On the PC whose 5.x database is the one you use: close WorkTimer 5.x, then
   push that database a last time, with its tokens —
   `uv run python scripts/push_to_staging.py --with-tokens --db <path to its worktimer.db>`
   from a checkout, or by hand:

   ```powershell
   ssh worktimer mkdir -p /opt/worktimer/data-pg/import
   scp "<its data folder>\worktimer.db" worktimer:/opt/worktimer/data-pg/import/worktimer.db
   scp "<its data folder>\.pat_key" worktimer:/opt/worktimer/data-pg/import/pat_key.v5
   ssh worktimer bash /opt/worktimer/scripts/staging.sh import
   ```

2. Check the report: `RESULT: match`, and no note that tracker tokens couldn't
   be read.
3. `ssh worktimer bash /opt/worktimer/scripts/staging.sh official` — from now
   on `import` refuses: it would replace everything entered on the server.
4. Stop entering time in 5.x; keep its database as a fallback. The nightly
   backups are on the server itself, so until they are copied off it, save a
   copy now and then with Settings → Download.

Updates later are `staging.sh up`: the database is a Docker volume, and what
Settings saves and the browsers' preferences are in `data-pg/`, so a rebuild
keeps them.

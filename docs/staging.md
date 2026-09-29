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
- **Backups:** the `backup` service backs the whole database and the notes
  and settings up daily into `/opt/worktimer/backups-pg` (newest 14, and each
  month's first for 12 months) — `scripts/pg_backup.sh`, below.

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

**On the server:** once a day the `backup` service writes into
`/opt/worktimer/backups-pg` ([scripts/pg_backup.sh](../scripts/pg_backup.sh)):

- `worktimer_<stamp>.dump` — the whole database, every user;
- `files_<stamp>.tar.gz` — the files in `data-pg/`: everyone's notes (with
  their images), settings and saved preferences. **Not** the token key
  (`.pat_key`), the preferences' `.storage_secret` or `.env`.

The newest 14 of each stay, and each month's first is also kept in
`backups-pg/monthly/` for 12 months (`BACKUP_KEEP`, `BACKUP_KEEP_MONTHLY`).
One extra backup now, e.g. before a risky change:

```bash
docker compose --profile postgres run --rm backup --once
```

**Off the server** — the server is the only live copy, so its backups must
not live only on it:

- **Hetzner Backups** (enabled 2026-09-29): in the Hetzner console, the
  server → *Backups*. An image of the whole disk once a day, the newest 7
  kept, about 20 % of the server's price. It holds everything, the token key
  and `.env` included: Postgres' Docker volume is a folder on that disk.
  (The console's "Volumes are not included" means Hetzner *Cloud Volumes*,
  extra disks — none is attached.) The images are **deleted with the
  server**: before deleting it, turn the one to keep into a snapshot.
  A manual snapshot (kept until deleted, about a cent per GB and month) is
  worth taking before big changes.
- **Copies on your PC:** from the WorkTimer checkout,

  ```powershell
  uv run python scripts/pull_backups.py --to "C:\Users\<you>\OneDrive\WorkTimer-backups"
  ```

  copies each backup not already there — dumps, file archives and the
  monthly ones (into `monthly\`). The newest 30 of each kind stay, and every
  monthly one (`--keep`, `--keep-monthly`); a OneDrive folder adds a cloud
  copy. To run it daily: Task Scheduler → *Create Basic Task* → daily, some
  time after lunch (the backup is written around midday) → *Start a
  program*: `uv`, arguments `run python scripts\pull_backups.py --to "<that
  folder>"`, *Start in*: the checkout folder.

**How far back:**

| From | Reaches back | Brings back |
|---|---|---|
| Hetzner Backups | 7 days | the whole server |
| `backups-pg/` | 14 days | the database and the files |
| `backups-pg/` inside the oldest Hetzner image | about 3 weeks | the same, via a temporary server made from the image |
| `backups-pg/monthly/` | 12 months, one per month | the same |
| The copies on your PC | as long as they are kept | the same, but no token key |

A mistake found late is usually one user's: rather than roll everyone back,
restore an older dump into a scratch database, copy that user's missing rows
across, and drop it:

```bash
docker compose --profile postgres run --rm backup createdb worktimer_scratch
docker compose --profile postgres run --rm backup \
  pg_restore -d worktimer_scratch /backups/monthly/worktimer_<month>.dump
# ... compare and copy, as the admin ...
docker compose --profile postgres run --rm backup dropdb worktimer_scratch
```

**Restore** (as the admin; the app stopped so nothing writes meanwhile), on
the server in `/opt/worktimer`. This rolls **every** user back:

```bash
docker compose --profile postgres stop worktimer-pg
docker compose --profile postgres run --rm backup \
  pg_restore --clean --if-exists -d worktimer /backups/worktimer_<stamp>.dump
tar -xzf backups-pg/files_<stamp>.tar.gz -C data-pg   # the files too, if needed
docker compose --profile postgres start worktimer-pg
```

`tar` can bring back one user's files only: add `./users/<key>` (or
`./notes ./config` for user 1). Files of the same name are overwritten;
newer ones stay.

From a copy on your PC (the server lost): set a new server up as above
(`staging.sh up`), `scp` the dump and the file archive into its
`/opt/worktimer/backups-pg/`, then restore the same way. The token key is
not in the copies: everyone enters their tracker tokens again, and saved
preferences start over. Checked 2026-09-29: a dump restored into a scratch
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

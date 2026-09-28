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
- **No tracker tokens, on purpose.** The weekly import leaves them out, so
  staging never talks to DevOps or Jira alongside 5.x.
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
uv run python scripts/push_to_staging.py
```

It takes a consistent snapshot of `data/worktimer.db` (SQLite's backup API —
safe while 5.x runs), copies it to the server, and runs
`scripts/staging.sh import` there: the importer replaces staging's data with
the snapshot and prints

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
| `scripts/staging.sh status` | containers, and the latest reports' results |
| `scripts/staging.sh up` | update: pull this branch, rebuild, restart |
| `docker compose --profile postgres logs -f worktimer-pg` | the app's log |
| `docker compose --profile postgres run --rm backup pg_restore --list /backups/<file>` | inspect a backup |

Restore a backup (as the admin, with the app stopped): see the header of
[scripts/pg_backup.sh](../scripts/pg_backup.sh).

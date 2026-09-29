#!/bin/sh
# Whole-database backups of the Postgres WorkTimer — compose's "backup"
# service (profile "postgres"). Every BACKUP_INTERVAL_SECONDS it runs pg_dump
# (custom format) as the admin role into /backups, keeping the newest
# BACKUP_KEEP. The postgres image's pg_dump always matches the server.
#
# Restore into the (stopped-app) database, as the admin:
#   docker compose --profile postgres run --rm backup \
#     pg_restore --clean --if-exists -d worktimer /backups/worktimer_<stamp>.dump
set -eu

# Given a command (the `run --rm backup pg_restore …` above), run that, not the loop.
[ "$#" -gt 0 ] && exec "$@"

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
keep="${BACKUP_KEEP:-14}"

while true; do
    file="/backups/worktimer_$(date +%Y-%m-%d_%H%M%S).dump"
    if pg_dump --format=custom --file="$file.partial"; then
        mv "$file.partial" "$file"
        echo "backup written: $file"
    else
        rm -f "$file.partial"
        echo "backup FAILED" >&2
    fi
    ls -1t /backups/worktimer_*.dump 2>/dev/null | tail -n +"$((keep + 1))" |
        while read -r old; do rm -f -- "$old"; done
    sleep "$interval"
done

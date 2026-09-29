#!/bin/sh
# Backups of the Postgres WorkTimer — compose's "backup" service (profile
# "postgres"). Every BACKUP_INTERVAL_SECONDS it runs pg_dump (custom format)
# of the whole database as the admin role, and archives the files beside it
# (./data-pg, mounted at /data: notes, settings, saved preferences — never the
# token key or the other secrets), into /backups. The newest BACKUP_KEEP of
# each stay; each month's first is also kept in /backups/monthly, the newest
# BACKUP_KEEP_MONTHLY there (0: all). The postgres image's pg_dump always
# matches the server.
#
# One backup now (e.g. before an import):
#   docker compose --profile postgres run --rm backup --once
#
# Restore into the (stopped-app) database, as the admin:
#   docker compose --profile postgres run --rm backup \
#     pg_restore --clean --if-exists -d worktimer /backups/worktimer_<stamp>.dump
set -eu
umask 077  # the dumps hold every user's data: root only

backups="${BACKUP_DIR:-/backups}"
data="${BACKUP_DATA_DIR:-/data}"
interval="${BACKUP_INTERVAL_SECONDS:-86400}"
keep="${BACKUP_KEEP:-14}"
keep_monthly="${BACKUP_KEEP_MONTHLY:-12}"
failed=0

# Delete all but the newest $2 files matching $1 (names carry the date).
prune() {
    [ "$2" -gt 0 ] || return 0
    ls -1r $1 2>/dev/null | tail -n +"$(($2 + 1))" |
        while read -r old; do rm -f -- "$old"; done
}

# Copy $1 to $2 unless the month already has its copy.
keep_for_month() {
    if [ -n "$1" ] && [ ! -e "$2" ]; then
        cp "$1" "$2.partial"
        mv "$2.partial" "$2"
    fi
}

backup() {
    stamp=$(date +%Y-%m-%d_%H%M%S)
    month=${stamp%-??_*}
    dump="$backups/worktimer_$stamp.dump"
    files="$backups/files_$stamp.tar.gz"

    if pg_dump --format=custom --file="$dump.partial"; then
        mv "$dump.partial" "$dump"
        echo "backup written: $dump"
    else
        rm -f "$dump.partial"
        dump=""
        failed=1
        echo "backup FAILED" >&2
    fi

    # tar exits 1 when a file changed while it was read (a note being saved):
    # the archive is still complete.
    status=0
    tar -czf "$files.partial" -C "$data" --exclude=.pat_key --exclude=.storage_secret \
        --exclude=./import --exclude=backups . || status=$?
    if [ "$status" -le 1 ]; then
        mv "$files.partial" "$files"
        echo "files written: $files"
    else
        rm -f "$files.partial"
        files=""
        failed=1
        echo "files backup FAILED" >&2
    fi

    mkdir -p "$backups/monthly"
    keep_for_month "$dump" "$backups/monthly/worktimer_$month.dump"
    keep_for_month "$files" "$backups/monthly/files_$month.tar.gz"

    prune "$backups/worktimer_*.dump" "$keep"
    prune "$backups/files_*.tar.gz" "$keep"
    prune "$backups/monthly/worktimer_*.dump" "$keep_monthly"
    prune "$backups/monthly/files_*.tar.gz" "$keep_monthly"
}

case "${1:-}" in
    --once) backup; exit "$failed" ;;
    "") ;;
    # Given a command (the `run --rm backup pg_restore …` above), run that, not the loop.
    *) exec "$@" ;;
esac

while true; do
    backup
    sleep "$interval"
done

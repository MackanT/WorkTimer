#!/bin/bash
# Phase 5 staging on the server (docs/staging.md): the Postgres WorkTimer,
# single-user, reached through an SSH tunnel. Run from anywhere; it works in
# the checkout it lives in.
#
#   staging.sh up       pull this branch, then build and start postgres,
#                       migrate, worktimer-pg and the backup service
#   staging.sh import   import data-pg/import/worktimer.db (a 5.x snapshot,
#                       put there by scripts/push_to_staging.py) over the
#                       account, compare the numbers, save the report
#   staging.sh gate     the last two reports: the gate passes when both
#                       matched, on the same code
#   staging.sh status   containers and the latest reports
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose --profile postgres)
reports=staging-reports

case "${1:-}" in
    up)
        git pull --ff-only
        "${compose[@]}" up -d --build migrate worktimer-pg backup
        "${compose[@]}" ps
        ;;
    import)
        file=data-pg/import/worktimer.db
        [ -f "$file" ] || { echo "no $file — push a 5.x snapshot first" >&2; exit 2; }
        mkdir -p "$reports"
        report="$reports/import_$(date +%Y-%m-%d_%H%M%S).txt"
        {
            echo "code: $(git rev-parse --short HEAD) ($(git log -1 --format=%cd --date=short))"
            echo "snapshot: $(stat -c %y "$file" | cut -d. -f1)"
        } > "$report"
        set +e
        "${compose[@]}" exec -T worktimer-pg uv run -m src.importer \
            /app/data/import/worktimer.db --replace --check-reports 2>&1 | tee -a "$report"
        status=${PIPESTATUS[0]}
        set -e
        rm -f "$file"  # the data is in Postgres now; no second copy lying around
        echo "report: $report"
        exit "$status"
        ;;
    gate)
        mapfile -t last < <(ls -1t "$reports"/import_*.txt 2>/dev/null | head -2)
        if [ "${#last[@]}" -lt 2 ]; then
            echo "gate: needs two weekly imports (have ${#last[@]})"; exit 1
        fi
        for r in "${last[@]}"; do echo "$(basename "$r"): $(head -1 "$r") — $(grep '^RESULT:' "$r" | tail -1)"; done
        codes=$(for r in "${last[@]}"; do head -1 "$r"; done | sort -u | wc -l)
        if grep -q '^RESULT: match$' "${last[0]}" && grep -q '^RESULT: match$' "${last[1]}" \
                && [ "$codes" -eq 1 ]; then
            echo "gate: PASSED — two consecutive imports matched, on the same code"
        else
            echo "gate: not yet — both must match, with no code change between them"; exit 1
        fi
        ;;
    status)
        "${compose[@]}" ps
        ls -1t "$reports"/import_*.txt 2>/dev/null | head -5 | while read -r r; do
            echo "$(basename "$r"): $(grep '^RESULT:' "$r" | tail -1)"; done
        ;;
    *)
        sed -n '2,15p' "$0"; exit 2
        ;;
esac

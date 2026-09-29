#!/bin/bash
# Phase 5 staging on the server (docs/staging.md): the Postgres WorkTimer,
# single-user, reached through an SSH tunnel. Run from anywhere; it works in
# the checkout it lives in.
#
#   staging.sh up       pull this branch, then build and start postgres,
#                       migrate, worktimer-pg and the backup service
#   staging.sh import   import data-pg/import/worktimer.db (a 5.x snapshot,
#                       put there by scripts/push_to_staging.py) over the
#                       account, compare the numbers, save the report; with
#                       data-pg/import/pat_key.v5 beside it (--with-tokens),
#                       the tracker tokens come along
#   staging.sh gate     the last two reports: the gate passes when both
#                       matched, on the same code
#   staging.sh official this instance becomes the official WorkTimer (the
#                       parallel run ends): from then on `import` refuses —
#                       it would replace everything entered here
#   staging.sh status   containers, whether official, the latest reports
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose --profile postgres)
reports=staging-reports
official=data-pg/OFFICIAL  # persisted, and outside git

case "${1:-}" in
    up)
        git pull --ff-only
        "${compose[@]}" up -d --build migrate worktimer-pg backup
        "${compose[@]}" ps
        ;;
    import)
        file=data-pg/import/worktimer.db
        key=data-pg/import/pat_key.v5
        # the data is in Postgres afterwards; no second copy (or 5.x key) lying around
        trap 'rm -f "$file" "$key"' EXIT
        if [ -f "$official" ]; then
            echo "refused: this is the official WorkTimer (since $(head -1 "$official")); an import would replace everything entered here" >&2
            exit 2
        fi
        [ -f "$file" ] || { echo "no $file — push a 5.x snapshot first" >&2; exit 2; }
        tokens=()
        [ -f "$key" ] && tokens=(--pat-key /app/data/import/pat_key.v5)
        mkdir -p "$reports"
        report="$reports/import_$(date +%Y-%m-%d_%H%M%S).txt"
        {
            echo "code: $(git rev-parse --short HEAD) ($(git log -1 --format=%cd --date=short))"
            echo "snapshot: $(stat -c %y "$file" | cut -d. -f1)"
        } > "$report"
        set +e
        "${compose[@]}" exec -T worktimer-pg uv run -m src.importer \
            /app/data/import/worktimer.db --replace --check-reports "${tokens[@]}" 2>&1 | tee -a "$report"
        status=${PIPESTATUS[0]}
        set -e
        # 0 and 3 wrote data: restart so the app reloads it (trackers connect)
        if [ "$status" -eq 0 ] || [ "$status" -eq 3 ]; then
            "${compose[@]}" restart worktimer-pg >/dev/null
        fi
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
    official)
        if [ -f "$official" ]; then
            echo "already official, since $(head -1 "$official")"; exit 0
        fi
        mkdir -p "$(dirname "$official")"
        echo "$(date '+%Y-%m-%d %H:%M') at $(git rev-parse --short HEAD)" > "$official"
        echo "official since $(head -1 "$official"): imports are refused from now on ($official)"
        ;;
    status)
        "${compose[@]}" ps
        [ -f "$official" ] && echo "official since $(head -1 "$official") — imports refused"
        ls -1t "$reports"/import_*.txt 2>/dev/null | head -5 | while read -r r; do
            echo "$(basename "$r"): $(grep '^RESULT:' "$r" | tail -1)"; done
        ;;
    *)
        sed -n '2,18p' "$0"; exit 2
        ;;
esac

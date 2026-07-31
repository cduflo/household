#!/usr/bin/env bash
# Refuse to publish anything identifying.
#
# This repo is public and GitHub Pages serves docs/. The protection is not the
# Pages source setting -- it is that no secret and no personal detail is ever
# committed. This script is that rule, executable.
#
# It caught three real leaks the first time it ran, including placeholder text
# in a form that had been written from the real household file.
#
# Usage:  ./scripts/check-public.sh          (working tree)
#         ./scripts/check-public.sh --staged (what is about to be committed)
set -uo pipefail
cd "$(dirname "$0")/.."

# Values that must never appear. Sourced from the untracked overlays so the
# list stays current without itself containing anything.
NEEDLES=()
for f in tools/*/owner.local.yaml tools/*/contacts.local.yaml; do
    [ -f "$f" ] || continue
    while IFS= read -r v; do
        [ ${#v} -ge 6 ] && NEEDLES+=("$v")
    done < <(grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+|\([0-9]{3}\) [0-9]{3}-[0-9]{4}' "$f")
done
# Plus the things a person would write by hand without thinking.
NEEDLES+=("service_role" "SUPABASE_DB_URL=postgresql" "SUPABASE_SERVICE_ROLE")

if [ "${1:-}" = "--staged" ]; then
    FILES=$(git diff --cached --name-only --diff-filter=ACM)
else
    FILES=$(git ls-files)
fi

hits=0
for f in $FILES; do
    [ -f "$f" ] || continue
    case "$f" in scripts/check-public.sh) continue ;; esac
    for n in "${NEEDLES[@]}"; do
        if grep -qF -- "$n" "$f" 2>/dev/null; then
            # A warning that says "never commit this" is not a leak.
            grep -qiE "never|must not|do not|bypass" <(grep -F -- "$n" "$f") && continue
            echo "  LEAK  $f  ::  $n"
            hits=$((hits + 1))
        fi
    done
done

if [ "$hits" -gt 0 ]; then
    echo "refusing: $hits occurrence(s) of untracked-overlay values in tracked files"
    exit 1
fi
echo "clean: no overlay values or service-role keys in tracked files"

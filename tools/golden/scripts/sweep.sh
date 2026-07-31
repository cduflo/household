#!/bin/bash
# Cron entry point: run the sweep, then snapshot the database.
#
# Nothing here pushes to git, deliberately. state.db holds notes, contact
# history and rendered drafts -- which interpolate the household paragraph, a
# phone number and a child's age. That material must never enter git history,
# so durability is a local encrypted-at-rest snapshot instead of a commit.
set -uo pipefail

REPO="/Users/chrisduflo/golden-watch"
BACKUP_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/golden-watch-backup"
KEEP=14

cd "$REPO" || exit 1

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

# A sweep that dies quietly into a gitignored log can be dead for weeks with no
# signal. Failures go to the same Telegram path the findings use.
fail() {
    .venv/bin/python - "$1" <<'PY' >/dev/null 2>&1
import sys
from gw import cli, notify
notify.send(cli.load_config(), "golden-watch: sweep FAILED — " + sys.argv[1])
PY
    exit 1
}

{
    echo "=== $(date -u +%FT%TZ) ==="

    .venv/bin/python -m gw.cli run || fail "gw run exited non-zero"

    mkdir -p "$BACKUP_DIR" || fail "cannot create backup dir"
    stamp=$(date -u +%F-%H%M)

    # sqlite3's backup API, not cp: it takes a consistent snapshot of a live
    # database. Copying the file while WAL frames are outstanding can produce a
    # torn database that only fails when you try to restore it.
    .venv/bin/python - "$BACKUP_DIR/state-$stamp.db" <<'PY' || fail "backup failed"
import sqlite3
import sys
src = sqlite3.connect("state.db")
dst = sqlite3.connect(sys.argv[1])
with dst:
    src.backup(dst)
dst.close()
src.close()
PY

    # Keep the most recent KEEP snapshots.
    ls -1t "$BACKUP_DIR"/state-*.db 2>/dev/null | tail -n +$((KEEP + 1)) \
        | while IFS= read -r old; do rm -f "$old"; done

    echo "backup: state-$stamp.db"
} >> sweep.log 2>&1

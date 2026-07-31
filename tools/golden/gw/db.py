"""Postgres state, shared by the sweep and the browser.

One database, two clients. The sweep and the CLI reach it over the session
pooler with psycopg; the static board reaches the same rows through PostgREST
with the anon key. Row Level Security is what makes the second one safe, and it
is proven in `tests/test_rls.py` rather than assumed.

The schema is no longer built here. It lives in `sql/001_schema.sql` and
`sql/002_rls.sql`, applied once to the project and re-applied verbatim to a
scratch database in tests, so there is exactly one definition of the tables and
no chance of the two drifting. That also removes the SQLite migration runner --
`PRAGMA user_version` has no Postgres equivalent and the whole apparatus existed
to work around DDL that Postgres expresses directly.

Connections are per-request and short-lived. That is what the session pooler is
for, and it keeps the sweep, the CLI and the local server from sharing state.

Direct connections (`db.<ref>.supabase.co`) are IPv6-only and will not work
from a machine without an IPv6 route. Use the session pooler string; the
transaction pooler on 6543 drops the session state that RLS impersonation and
`SET ROLE` depend on.
"""
import json
import os
import pathlib
import time

import psycopg
from psycopg.rows import dict_row

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
ENV_FILE = ROOT / ".env.supabase"


def _load_env():
    """Read .env.supabase without a dependency. Values never get logged."""
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def dsn():
    """Environment wins, so tests and CI can point somewhere scratch."""
    return os.environ.get("SUPABASE_DB_URL") or _load_env().get("SUPABASE_DB_URL", "")


def connect(url=None):
    con = psycopg.connect(url or dsn(), connect_timeout=20, row_factory=dict_row)
    con.autocommit = True
    return con


def apply_schema(con):
    """Run the same SQL the live project runs. Used by tests and `gw init`."""
    for name in ("001_schema.sql", "002_rls.sql"):
        con.execute((SQL_DIR / name).read_text())


# ---------------------------------------------------------------- snapshots

def get_snapshot(con, key):
    return con.execute("SELECT * FROM snapshot WHERE key = %s", (key,)).fetchone()


def put_snapshot(con, key, url, text, digest, http_status=None, error=None):
    con.execute(
        """INSERT INTO snapshot (key, url, text, digest, fetched_at, http_status, error)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (key) DO UPDATE SET
             url=excluded.url, text=excluded.text, digest=excluded.digest,
             fetched_at=excluded.fetched_at, http_status=excluded.http_status,
             error=excluded.error""",
        (key, url, text, digest, time.time(), http_status, error),
    )


# ---------------------------------------------------------------- findings

RENOTIFY_DAYS = 7


def add_finding(con, key, label, url, kind, score, excerpt):
    row = con.execute(
        """INSERT INTO finding (key, label, url, kind, score, excerpt, found_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (key, label, url, kind, score, excerpt, time.time()),
    ).fetchone()
    return row["id"]


def upsert_nudge(con, key, label, url, score, excerpt):
    """One open nudge per key.

    This was a plain INSERT, which minted a fresh unnotified row on every sweep
    -- so Telegram re-alerted the same overdue clubs twice a day forever and the
    board grew without bound.

    `found_at` is deliberately never updated: it means "first went due", the
    excerpt is written against it, and reusing it as a re-notify clock would
    destroy the only signal for how long something has been waiting. That is
    what `last_notified_at` is for.
    """
    now = time.time()
    row = con.execute(
        """INSERT INTO finding (key, label, url, kind, score, excerpt, found_at)
           VALUES (%s,%s,%s,'nudge',%s,%s,%s)
           ON CONFLICT (key) WHERE kind = 'nudge' AND dismissed = 0 DO UPDATE SET
             label = excluded.label, url = excluded.url,
             score = excluded.score, excerpt = excluded.excerpt,
             notified = CASE
               WHEN finding.last_notified_at IS NULL THEN finding.notified
               WHEN %s - finding.last_notified_at > %s THEN 0
               ELSE finding.notified END
           RETURNING id""",
        (key, label, url, score, excerpt, now, now, RENOTIFY_DAYS * 86400),
    ).fetchone()
    return row["id"]


def reconcile_nudges(con, due_keys):
    """Retire nudges whose condition has cleared.

    `build_findings` only ever adds. Without this the queue is structurally
    incapable of reaching zero -- a club stays on the board forever after you
    have written to it, and a board that is always full is one you stop reading.
    """
    keys = list(due_keys)
    cur = con.execute(
        "UPDATE finding SET dismissed = 1"
        " WHERE kind = 'nudge' AND dismissed = 0 AND NOT (key = ANY(%s))",
        (keys,),
    )
    return cur.rowcount


def dismiss(con, finding_id):
    return con.execute("UPDATE finding SET dismissed = 1 WHERE id = %s",
                       (finding_id,)).rowcount


def unnotified(con):
    return con.execute(
        "SELECT * FROM finding WHERE notified = 0 AND dismissed = 0"
        " ORDER BY score DESC, found_at DESC").fetchall()


def mark_notified(con, ids):
    con.execute(
        "UPDATE finding SET notified = 1, last_notified_at = %s WHERE id = ANY(%s)",
        (time.time(), list(ids)))


def recent_findings(con, limit=60):
    return con.execute(
        "SELECT * FROM finding WHERE dismissed = 0 ORDER BY found_at DESC LIMIT %s",
        (limit,)).fetchall()


# ---------------------------------------------------------------- contact

def log_contact(con, target_key, target_type, direction, channel, summary=""):
    con.execute(
        """INSERT INTO contact (target_key, target_type, direction, channel, summary, at)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (target_key, target_type, direction, channel, summary, time.time()))


def last_contact(con, target_key):
    return con.execute(
        "SELECT * FROM contact WHERE target_key = %s ORDER BY at DESC LIMIT 1",
        (target_key,)).fetchone()


def contact_history(con, target_key):
    return con.execute(
        "SELECT * FROM contact WHERE target_key = %s ORDER BY at DESC",
        (target_key,)).fetchall()


# ---------------------------------------------------------------- ofa

def put_ofa(con, prefix, payload):
    con.execute(
        """INSERT INTO ofa_check (kennel_prefix, checked_at, payload) VALUES (%s,%s,%s)
           ON CONFLICT (kennel_prefix) DO UPDATE SET
             checked_at=excluded.checked_at, payload=excluded.payload""",
        (prefix, time.time(), json.dumps(payload)))


def get_ofa(con, prefix):
    row = con.execute("SELECT * FROM ofa_check WHERE kennel_prefix = %s",
                      (prefix,)).fetchone()
    if not row:
        return None
    return {"checked_at": row["checked_at"], "payload": json.loads(row["payload"])}


# ---------------------------------------------------------------- runs

def log_run(con, checked, changed, alerted, errors):
    con.execute(
        "INSERT INTO run_log (at, checked, changed, alerted, errors)"
        " VALUES (%s,%s,%s,%s,%s)",
        (time.time(), checked, changed, alerted, errors))


def last_run(con):
    return con.execute("SELECT * FROM run_log ORDER BY at DESC LIMIT 1").fetchone()

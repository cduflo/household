import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gw import db  # noqa: E402

#: A scratch Postgres, never the live project. `gw db` in CI or:
#:   docker run -d --name gw-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=gw \
#:       -p 55432:5432 postgres:16
TEST_DSN = os.environ.get("GW_TEST_DSN", "postgresql://postgres:dev@127.0.0.1:55432/gw")

# Force every no-argument db.connect() onto the scratch database, before any
# test imports anything. Without this the server's own `db.connect()` resolves
# through .env.supabase to the LIVE project, and a test that truncates tables
# would wipe the real board. `db.dsn()` reads the environment first precisely
# so this override works.
os.environ["SUPABASE_DB_URL"] = TEST_DSN

TABLES = ["snapshot", "finding", "contact", "ofa_check", "run_log",
          "entity_state", "note", "checklist", "event", "commitment",
          "litter", "dog", "template", "household_member"]


@pytest.fixture(scope="session")
def _database():
    """Build the schema once from the same SQL the live project runs.

    Applying sql/*.sql rather than a Python-side copy is the point: there is one
    definition of the tables, so the tests cannot pass against a schema that
    production does not have.
    """
    psycopg = pytest.importorskip("psycopg")
    try:
        con = psycopg.connect(TEST_DSN, connect_timeout=5)
    except psycopg.OperationalError:
        pytest.skip("no scratch Postgres; see tests/conftest.py")
    con.autocommit = True
    con.execute("drop schema public cascade; create schema public;")
    for role in ("anon", "authenticated"):
        con.execute(f"do $$ begin if not exists (select 1 from pg_roles where "
                    f"rolname='{role}') then create role {role} nologin; end if; end $$")
    db.apply_schema(con)
    yield con
    con.close()


@pytest.fixture
def con(_database):
    """A clean database per test.

    TRUNCATE rather than a fresh schema: it is two orders of magnitude faster
    and resets the identity sequences, which several tests depend on.
    """
    _database.execute(
        f"truncate {', '.join(TABLES)} restart identity cascade")
    connection = db.connect(TEST_DSN)
    yield connection
    connection.close()


def test_tests_never_point_at_the_live_project():
    """A canary. If this ever fails, a test run is about to truncate the real
    board -- the scratch DSN must never be the Supabase pooler."""
    import os
    assert "pooler.supabase.com" not in os.environ.get("SUPABASE_DB_URL", "")
    assert db.dsn() == TEST_DSN

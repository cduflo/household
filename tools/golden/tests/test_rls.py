"""The security proof.

On Supabase the anon key is embedded in public JavaScript. It is not a secret.
RLS is the only thing between that public key and the data, so these tests are
the whole security story and they run before anything depends on them.

They connect as the same unprivileged roles Supabase uses (`anon` for a
signed-out visitor, `authenticated` for a signed-in one) and set
`request.jwt.claims` exactly as Supabase does after verifying a Google JWT.

Skipped automatically when no local Postgres is running:
    docker run -d --name gw-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=gw \
        -p 55432:5432 postgres:16
"""
import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

DSN = os.environ.get("GW_TEST_DSN", "postgresql://postgres:dev@127.0.0.1:55432/gw")
SQL = Path(__file__).resolve().parent.parent / "sql"

OWNER = "chris@example.com"
MEMBER = "kaele@example.com"
STRANGER = "attacker@gmail.com"


def _admin():
    try:
        return psycopg.connect(DSN, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("no local Postgres; see module docstring")


@pytest.fixture(scope="module")
def database():
    con = _admin()
    with con.cursor() as cur:
        # This fixture drops the schema. That is fine against a scratch
        # container and catastrophic against a live project, and the DSN is
        # just an environment variable -- one careless export away from
        # pointing at production. So: refuse unless the database is empty, or
        # somebody has explicitly said they mean it.
        # A scratch container is fair game -- that is what it is for. A hosted
        # Supabase project is not, and the DSN is an environment variable one
        # careless export away from pointing at the real board.
        hosted = "supabase.co" in DSN or "supabase.com" in DSN
        if hosted and os.environ.get("GW_ALLOW_DESTRUCTIVE") != "1":
            pytest.skip(
                f"refusing to drop the schema of a hosted project ({DSN.rsplit('@', 1)[-1]})."
                " Set GW_ALLOW_DESTRUCTIVE=1 only if you are certain it is disposable.")
        cur.execute("drop schema public cascade; create schema public;")
        # The two roles Supabase provides. anon = signed out, authenticated =
        # signed in. Neither may bypass RLS. They must exist before the
        # policies that name them.
        for role in ("anon", "authenticated"):
            cur.execute(
                f"do $$ begin if not exists (select 1 from pg_roles "
                f"where rolname = '{role}') then create role {role} nologin; "
                f"end if; end $$")
        for name in ("001_schema.sql", "002_rls.sql"):
            cur.execute((SQL / name).read_text())
        # Deliberately NO blanket grant here. Production has "Automatically
        # expose new tables" off, so grants come only from 002_rls.sql. A
        # fixture that granted everything would hide a table missing from that
        # list — the test would pass and the real project would 401.
        cur.execute("insert into household_member (email, role) values (%s,'owner')",
                    (OWNER,))
        cur.execute("insert into household_member (email, role) values (%s,'household')",
                    (MEMBER,))
        cur.execute(
            "insert into note (kind, key, author, body, pinned, at)"
            " values ('breeder','meirzah',%s,'they have a September litter',0,1.0)",
            (OWNER,))
        cur.execute(
            "insert into entity_state (kind, key, stage, updated_at)"
            " values ('breeder','meirzah','talking',1.0)")
    yield con
    con.close()


def as_user(database, email, role="authenticated"):
    """A session exactly as Supabase presents one: an unprivileged role plus
    verified JWT claims."""
    cur = database.cursor()
    cur.execute(f"set role {role}")
    # Session-scoped, not transaction-scoped: this connection is autocommit, so
    # a `true` (local) setting would be discarded the instant the statement
    # ended and every request would look anonymous. Supabase sets it per
    # transaction; the visible behaviour is the same.
    claims = "" if email is None else f'{{"email":"{email}"}}'
    cur.execute("select set_config('request.jwt.claims', %s, false)", (claims,))
    return cur


def reset(database):
    with database.cursor() as cur:
        cur.execute("reset role")
        cur.execute("select set_config('request.jwt.claims', '', false)")


# ---------------------------------------------------------------- denial

@pytest.mark.parametrize("table", [
    "note", "entity_state", "finding", "contact", "event", "dog", "litter",
    "commitment", "checklist", "snapshot", "template", "household_member",
])
def test_anonymous_reads_nothing_from_any_table(database, table):
    """The failure that matters: anyone finds the URL, lifts the anon key out
    of the JavaScript, and queries directly."""
    cur = as_user(database, None, role="anon")
    try:
        cur.execute(f"select count(*) from {table}")
        assert cur.fetchone()[0] == 0, f"{table} is readable anonymously"
    finally:
        reset(database)


def test_a_valid_google_account_that_is_not_ours_reads_nothing(database):
    """Signing in with Google is not authorisation. Anyone on earth can do it."""
    cur = as_user(database, STRANGER)
    try:
        cur.execute("select count(*) from note")
        assert cur.fetchone()[0] == 0
    finally:
        reset(database)


def test_a_stranger_cannot_write(database):
    cur = as_user(database, STRANGER)
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("insert into note (kind,key,body,at)"
                        " values ('breeder','x','injected',1.0)")
    finally:
        database.rollback()
        reset(database)


def test_the_allowlist_itself_is_not_public(database):
    """It contains two real email addresses."""
    cur = as_user(database, None, role="anon")
    try:
        cur.execute("select count(*) from household_member")
        assert cur.fetchone()[0] == 0
    finally:
        reset(database)


# ---------------------------------------------------------------- access

def test_household_member_reads_the_board(database):
    cur = as_user(database, MEMBER)
    try:
        cur.execute("select body from note")
        assert "September litter" in cur.fetchone()[0]
    finally:
        reset(database)


def test_household_member_can_write_a_note(database):
    cur = as_user(database, MEMBER)
    try:
        cur.execute("insert into note (kind,key,author,body,at)"
                    " values ('breeder','meirzah',%s,'called them',1.0)", (MEMBER,))
        cur.execute("select count(*) from note where author = %s", (MEMBER,))
        assert cur.fetchone()[0] == 1
    finally:
        database.rollback()
        reset(database)


def test_owner_reads_the_board(database):
    cur = as_user(database, OWNER)
    try:
        cur.execute("select count(*) from entity_state")
        assert cur.fetchone()[0] == 1
    finally:
        reset(database)


# ---------------------------------------------------------------- allowlist

def test_household_member_cannot_add_an_accomplice(database):
    """She may use the board; she may not widen who can."""
    cur = as_user(database, MEMBER)
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("insert into household_member (email, role)"
                        " values ('friend@gmail.com','household')")
    finally:
        database.rollback()
        reset(database)


def test_owner_can_add_a_member(database):
    cur = as_user(database, OWNER)
    try:
        cur.execute("insert into household_member (email, role)"
                    " values ('newperson@example.com','household')")
        cur.execute("select count(*) from household_member")
        assert cur.fetchone()[0] == 3
    finally:
        database.rollback()
        reset(database)


def test_email_matching_is_case_insensitive(database):
    """Google returns whatever case the account was created with."""
    cur = as_user(database, "Kaele@Example.COM")
    try:
        cur.execute("select count(*) from note")
        assert cur.fetchone()[0] >= 1
    finally:
        reset(database)


def test_empty_claims_are_not_treated_as_a_member(database):
    """A malformed or absent JWT must not match a row whose email is ''."""
    with database.cursor() as cur:
        cur.execute("reset role")
        cur.execute("insert into household_member (email, role)"
                    " values ('', 'household') on conflict do nothing")
    cur = as_user(database, None, role="anon")
    try:
        cur.execute("select count(*) from note")
        assert cur.fetchone()[0] == 0
    finally:
        reset(database)
        with database.cursor() as c:
            c.execute("delete from household_member where email = ''")


def test_the_allowlist_cannot_bootstrap_itself_through_the_api(database):
    """The bug 003_seed.sql exists to document.

    is_owner() reads household_member, and the write policy on
    household_member requires is_owner(). While the table is empty nobody
    qualifies, so the first row can never be inserted through the API -- it has
    to come from the SQL editor, which runs as the table owner.
    """
    with database.cursor() as cur:
        cur.execute("reset role")
        cur.execute("create temp table saved as select * from household_member")
        cur.execute("delete from household_member")

    cur = as_user(database, OWNER)
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("insert into household_member (email, role)"
                        " values (%s, 'owner')", (OWNER,))
    finally:
        database.rollback()
        reset(database)
        with database.cursor() as c:
            c.execute("insert into household_member select * from saved")
            c.execute("drop table saved")


def test_the_owner_role_can_seed_it_as_the_sql_editor_does(database):
    """And the escape hatch works: ENABLE (not FORCE) row level security means
    the table owner is not subject to the policy."""
    with database.cursor() as cur:
        cur.execute("reset role")
        cur.execute("select count(*) from household_member")
        assert cur.fetchone()[0] >= 2


def test_every_table_is_covered_by_policies_and_grants():
    """The bug this catches: adding a table to the grant list but not the
    policy list (or the reverse). Grants decide what is reachable, policies
    decide what comes back -- a table in one list and not the other is either
    exposed or unusable, and both fail quietly."""
    import re
    rls = (SQL / "002_rls.sql").read_text()
    lists = [set(re.findall(r"'(\w+)'", block))
             for block in re.findall(r"array\[([^\]]+)\]", rls)]
    assert len(lists) == 2, "expected a policy list and a grant list"
    assert lists[0] == lists[1], f"lists disagree: {lists[0] ^ lists[1]}"

    declared = set(re.findall(r"create table if not exists (\w+)",
                              (SQL / "001_schema.sql").read_text()))
    assert declared == lists[0], f"not covered: {declared ^ lists[0]}"

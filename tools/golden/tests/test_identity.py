"""Identity and role gating on the command station.

The rule these protect: Kaele sees the board — findings, breeders, clubs, notes,
stages. She does not see the drafts, because a draft interpolates the household
paragraph, a phone number and a child's age from `owner.local.yaml`. And she
cannot trigger a sweep, because that fires a crawl at six volunteer-run websites
whose owners never asked to be scraped.
"""
import json
import threading
import urllib.error
import urllib.request

import pytest

from gw import identity, db, serve


SHARED = {
    "owner": {"name": "Chris", "base": "West Hartford, CT",
              "phone": "(860) 555-0100", "household": "two adults at home",
              "dog_history": "huskies and wheatens"},
    "access": {"owners": ["chris@example.com"], "household": ["kaele@example.com"]},
    "preferences": {"target_home_date": "2026-10-15"},
    "clubs": [{"key": "sbgrc", "name": "SBGRC", "url": "http://s",
               "referral_email": "a@b.com", "method": "email", "recontact_days": 45}],
    "breeders": [{"key": "meirzah", "name": "Meirzah", "site": "http://m",
                  "status": "researching", "line": "unknown"}],
}
LOCAL = {**SHARED, "access": {}}

OWNER, MEMBER = "chris@example.com", "kaele@example.com"


# ---------------------------------------------------------------- unit

def test_unshared_install_treats_everyone_as_owner():
    """The laptop case. No allowlist means nothing is proxied, which means
    loopback only -- so there is nobody else to be."""
    assert identity.identify({}, LOCAL)["role"] == "owner"


def test_once_shared_a_missing_header_is_a_denial():
    assert identity.identify({}, SHARED) is None


def test_stranger_refused_even_with_a_valid_google_account():
    assert identity.identify({"X-Forwarded-Email": "nope@gmail.com"}, SHARED) is None


def test_roles_resolve_case_insensitively():
    assert identity.identify({"X-Forwarded-Email": "Chris@Example.com"},
                             SHARED)["role"] == "owner"
    assert identity.identify({"X-Forwarded-Email": "kaele@example.com"},
                             SHARED)["role"] == "household"


def test_household_cannot_satisfy_an_owner_requirement():
    assert not identity.allows({"email": "k", "role": "household"}, "owner")


# ---------------------------------------------------------------- live

@pytest.fixture
def server(tmp_path, monkeypatch, con):
    from gw import cli
    scratch = tmp_path / "config.yaml"
    scratch.write_text("breeders:\n")
    monkeypatch.setattr(cli, "CONFIG", scratch)
    httpd = serve.serve(lambda: SHARED, port=0)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = serve.make_handler(lambda: SHARED, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def call(base, path, payload=None, method="POST", email=None):
    data = json.dumps(payload or {}).encode() if method == "POST" else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-GW", "1")
    if email:
        req.add_header("X-Forwarded-Email", email)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            raw = res.read()
            try:
                return res.status, json.loads(raw or b"{}")
            except ValueError:
                return res.status, {"html": raw.decode()}
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}


def test_unauthenticated_gets_nothing(server):
    assert call(server, "/", method="GET")[0] == 403


def test_stranger_gets_nothing(server):
    assert call(server, "/", method="GET", email="nope@gmail.com")[0] == 403


def test_household_sees_the_board(server):
    status, body = call(server, "/", method="GET", email=MEMBER)
    assert status == 200 and "Meirzah" in body["html"]


def test_household_cannot_read_a_draft(server):
    """The draft carries the phone number, the household paragraph and a
    child's age. It must not render for her, server-side."""
    status, _ = call(server, "/api/draft", {"kind": "club", "key": "sbgrc"},
                     email=MEMBER)
    assert status == 403


def test_owner_can_read_a_draft(server):
    status, body = call(server, "/api/draft", {"kind": "club", "key": "sbgrc"},
                        email=OWNER)
    assert status == 200 and "text" in body


def test_household_cannot_trigger_a_crawl(server):
    """A sweep fires at six volunteer-run sites. That trigger is owner-only."""
    assert call(server, "/api/sweep", {}, email=MEMBER)[0] == 403


def test_household_can_still_do_the_collaborative_things(server):
    """The point of sharing: she can move a stage, take a note, log a reply."""
    assert call(server, "/api/stage",
                {"kind": "breeder", "key": "meirzah", "stage": "talking"},
                email=MEMBER)[0] == 200
    assert call(server, "/api/note",
                {"kind": "breeder", "key": "meirzah", "body": "called them"},
                email=MEMBER)[0] == 200
    assert call(server, "/api/contact",
                {"kind": "breeder", "key": "meirzah", "direction": "in",
                 "summary": "they replied"}, email=MEMBER)[0] == 200


def test_the_page_never_contains_owner_only_material(server):
    """Belt and braces: grep the rendered artifact for the actual values."""
    _, body = call(server, "/", method="GET", email=MEMBER)
    html = body["html"]
    assert "555-0100" not in html
    assert "two adults at home" not in html
    assert "huskies and wheatens" not in html


def test_notes_record_who_wrote_them(server):
    """Two people means authorship stops being optional."""
    call(server, "/api/note", {"kind": "breeder", "key": "meirzah",
                               "body": "she seemed cagey"}, email=MEMBER)
    con = db.connect()
    row = con.execute("SELECT author FROM note ORDER BY id DESC LIMIT 1").fetchone()
    assert row["author"] == MEMBER

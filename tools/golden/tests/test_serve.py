"""The HTTP surface.

The security assertions here are the point. The threat model is a web page in
another tab, and the page renders a phone number and a child's age — so the
Host check, the X-GW requirement and the CSP are load-bearing, not decoration.
"""
import json
import threading
import urllib.error
import urllib.request

import pytest

from gw import crm, db, serve


CFG = {
    "owner": {"name": "Chris", "base": "West Hartford, CT", "phone": "(860) 555-0100",
              "household": "two adults at home", "dog_history": "huskies and wheatens"},
    "preferences": {"target_home_date": "2026-10-15", "sex": "female",
                    "sex_is_flexible": False},
    "clubs": [{"key": "sbgrc", "name": "SBGRC", "url": "http://s",
               "referral_email": "a@b.com", "referral_contact": "Pat Example",
               "method": "email", "recontact_days": 45}],
    "breeders": [{"key": "meirzah", "name": "Meirzah", "site": "http://m",
                  "status": "researching", "line": "unknown"}],
}


@pytest.fixture
def server(tmp_path, monkeypatch, con):
    # `POST /api/breeder` appends to config.yaml by design (raw text, to keep
    # the comments). Without this redirect the suite writes to the real one --
    # which it did, twice, before this line existed.
    from gw import cli
    scratch = tmp_path / "config.yaml"
    scratch.write_text("breeders:\n")
    monkeypatch.setattr(cli, "CONFIG", scratch)
    httpd = serve.serve(lambda: CFG, port=0)
    port = httpd.server_address[1]
    # The handler closes over the port for its Host allowlist, so rebuild it
    # now that the OS has assigned one.
    httpd.RequestHandlerClass = serve.make_handler(lambda: CFG, port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", port
    httpd.shutdown()
    httpd.server_close()


def call(base, path, payload=None, method="POST", headers=None, host=None):
    url = base + path
    data = json.dumps(payload or {}).encode() if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            raw = res.read()
            try:
                parsed = json.loads(raw or b"{}")
            except ValueError:
                parsed = {"html": raw.decode("utf-8", "replace")}
            return res.status, parsed, dict(res.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body or b"{}")
        except ValueError:
            parsed = {"raw": body[:200].decode("utf-8", "replace")}
        return exc.code, parsed, dict(exc.headers)


GW = {"X-GW": "1"}


# ---------------------------------------------------------------- security

def test_a_write_without_the_custom_header_is_refused(server):
    """The real CSRF control: a cross-origin form POST cannot set X-GW, so it
    is forced into a preflight it can never pass."""
    base, _ = server
    status, body, _ = call(base, "/api/stage",
                           {"kind": "breeder", "key": "meirzah", "stage": "contacted"})
    assert status == 403 and "X-GW" in body["error"]


def test_a_forged_host_is_refused_before_routing(server):
    """Without this, a hostile page resolves its own domain to 127.0.0.1 and
    talks to this server as same-origin."""
    base, _ = server
    status, _, _ = call(base, "/", method="GET", host="evil.com")
    assert status == 421


def test_a_host_prefix_attack_is_refused(server):
    """`startswith("127.0.0.1")` would accept this."""
    base, port = server
    status, _, _ = call(base, "/", method="GET", host=f"127.0.0.1:{port}.evil.com")
    assert status == 421


def test_the_draft_endpoint_also_requires_the_header(server):
    """It returns a phone number and a child's age, so it is not a plain read."""
    base, _ = server
    status, _, _ = call(base, "/api/draft", {"kind": "club", "key": "sbgrc"})
    assert status == 403


def test_security_headers_are_on_every_response(server):
    base, _ = server
    _, _, headers = call(base, "/", method="GET")
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert "no-store" in headers["Cache-Control"]
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_a_non_json_content_type_is_refused(server):
    """`<form enctype="text/plain">` can forge a body json.loads accepts."""
    base, _ = server
    req = urllib.request.Request(base + "/api/stage", data=b'{"kind":"breeder"}',
                                 method="POST")
    req.add_header("Content-Type", "text/plain")
    req.add_header("X-GW", "1")
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "should have been refused"
    except urllib.error.HTTPError as exc:
        assert exc.code == 415


def test_an_oversized_body_is_refused(server):
    base, _ = server
    status, _, _ = call(base, "/api/note",
                        {"kind": "breeder", "key": "meirzah", "body": "x" * 300000},
                        headers=GW)
    assert status == 413


def test_errors_never_leak_a_traceback(server):
    base, _ = server
    status, body, _ = call(base, "/api/stage",
                           {"kind": "breeder", "key": "m", "stage": "not-a-stage"},
                           headers=GW)
    assert status >= 400
    assert "Traceback" not in json.dumps(body)


# ---------------------------------------------------------------- behaviour

def test_the_dashboard_renders(server):
    base, _ = server
    req = urllib.request.Request(base + "/", method="GET")
    with urllib.request.urlopen(req, timeout=5) as res:
        html = res.read().decode()
    assert "Golden Watch" in html
    assert "Meirzah" in html


def test_get_root_does_not_write_a_file(server, tmp_path, monkeypatch):
    """The old build_dashboard wrote the file as a side effect of reading, so
    every page load would rewrite it."""
    from gw import cli
    out = tmp_path / "should-not-appear.html"
    monkeypatch.setattr(cli, "OUT", out)
    base, _ = server
    urllib.request.urlopen(base + "/", timeout=5).read()
    assert not out.exists()


def test_stage_change_round_trips(server):
    base, _ = server
    status, body, _ = call(base, "/api/stage",
                           {"kind": "breeder", "key": "meirzah", "stage": "talking"},
                           headers=GW)
    assert status == 200 and body["stage"] == "talking"
    con = db.connect()
    assert crm.get_state(con, "breeder", "meirzah")["stage"] == "talking"


def test_draft_reports_unfilled_blanks_without_blocking(server):
    """Warn, never gate: blocking the *log* action over a stale textarea just
    teaches you to type filler into the one line that must be true."""
    base, _ = server
    status, body, _ = call(base, "/api/draft",
                           {"kind": "breeder", "key": "meirzah"}, headers=GW)
    assert status == 200
    assert body["blanks"], "the required specific sentence should be reported"
    assert "ONE specific" in " ".join(body["blanks"])


def test_logging_a_sent_email_advances_stage_and_flips_the_ball(server):
    base, _ = server
    call(base, "/api/contact", {"kind": "breeder", "key": "meirzah",
                                "direction": "out", "summary": "intro"}, headers=GW)
    con = db.connect()
    state = crm.get_state(con, "breeder", "meirzah")
    assert state["stage"] == "contacted"
    assert state["ball"] == "them"


def test_logging_a_reply_puts_the_ball_back_on_us(server):
    """'They asked me a question three days ago' is a five-alarm state that a
    last-contacted timestamp renders as 'all good'."""
    base, _ = server
    call(base, "/api/contact", {"kind": "breeder", "key": "meirzah",
                                "direction": "in", "summary": "asked about our yard"},
         headers=GW)
    con = db.connect()
    state = crm.get_state(con, "breeder", "meirzah")
    assert state["ball"] == "us"
    assert state["stage"] == "talking"


def test_adding_a_breeder_records_provenance(server):
    """'Rose at CRVGRC suggested I write to you' is the strongest opening line
    available, so where a name came from is worth a pinned note."""
    base, _ = server
    status, body, _ = call(base, "/api/breeder",
                           {"name": "Sunfire Goldens", "provenance": "Rose at CRVGRC"},
                           headers=GW)
    assert status == 200
    con = db.connect()
    notes = crm.notes(con, "breeder", body["key"])
    assert notes and notes[0]["pinned"] == 1 and "Rose" in notes[0]["body"]


def test_a_breeder_key_cannot_collide_with_a_club_key(server):
    base, _ = server
    status, body, _ = call(base, "/api/breeder",
                           {"name": "Anything", "key": "sbgrc"}, headers=GW)
    assert status == 400 and "club key" in body["error"]


def test_commitment_rejects_a_vague_date(server):
    base, _ = server
    status, _, _ = call(base, "/api/commitment",
                        {"on_date": "sometime in September", "what": "clinic"},
                        headers=GW)
    assert status == 400


def test_appending_a_duplicate_key_is_refused_at_the_file(server):
    """The caller checks a config it loaded earlier; this checks the file
    actually being appended to. The suite wrote two identical breeders into the
    real config.yaml before this guard existed."""
    base, _ = server
    call(base, "/api/breeder", {"name": "Twice Kennels"}, headers=GW)
    status, body, _ = call(base, "/api/breeder", {"name": "Twice Kennels"}, headers=GW)
    assert status == 400 and "already" in body["error"]


def test_tests_never_touch_the_real_config(server):
    """A canary: if the CONFIG monkeypatch is ever dropped, this fails loudly
    instead of silently editing the user's file."""
    from pathlib import Path
    from gw import cli
    assert cli.CONFIG != Path(__file__).resolve().parent.parent / "config.yaml"

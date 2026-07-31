"""Localhost command station.

The threat model is not "attacker on the network". It is "a web page in another
tab talks to my localhost server", plus "personal data escapes the machine".
Both are handled here rather than in the browser:

* Bound to 127.0.0.1 explicitly. This laptop joins coffee-shop wifi.
* Every request, including GET and HEAD, passes an exact `Host` match before
  routing. Without it a hostile page can resolve its own domain to 127.0.0.1
  and talk to this server as same-origin. A `startswith` check would accept
  `Host: 127.0.0.1.evil.com`, so it is a membership test against a 2-element set.
* Writes and anything returning personal data require `X-GW: 1`. A custom
  header cannot be set by a form POST, so it forces a CORS preflight that
  never succeeds cross-origin. This is the actual CSRF control; the JSON
  content-type check is defence in depth, because `<form enctype="text/plain">`
  can forge a body that `json.loads` accepts.
* Strict CSP with `frame-ancestors 'none'`. The dashboard renders text scraped
  from watched breeder sites, so an XSS here would have full write access to
  every endpoint *and* could read the drafts, which carry a phone number and a
  child's age.
* `Cache-Control: no-store` everywhere. Drafts must not land in the browser's
  disk cache or history.

One connection per request. `sqlite3` connections have thread affinity and this
server is threaded, so a shared connection raises `ProgrammingError` on the
first concurrent request. Connecting per request costs ~0.4ms including the
schema check, which is free at this volume.
"""
import json
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import crm, dashboard, db, identity, model, nudge

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 256 * 1024

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; "
        "base-uri 'none'"),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store, max-age=0",
}


class Error(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- handlers
#
# Each takes (payload, con, cfg) and returns a JSON-able dict. Keeping them free
# of HTTP means the router can be swapped for Flask later without touching them,
# and they can be tested by calling them.

def _entity(payload):
    kind = payload.get("kind")
    key = payload.get("key")
    if kind not in ("club", "breeder") or not key:
        raise Error("kind must be club or breeder, and key is required")
    return kind, key


def _label_for(cfg, kind, key):
    bucket = "clubs" if kind == "club" else "breeders"
    for item in cfg.get(bucket, []):
        if item["key"] == key:
            return item.get("name", key)
    return key


def h_stage(payload, con, cfg, user):
    kind, key = _entity(payload)
    stage = crm.set_stage(con, kind, key, payload.get("stage"),
                          _label_for(cfg, kind, key))
    return {"stage": stage}


def h_rating(payload, con, cfg, user):
    kind, key = _entity(payload)
    return {"rating": crm.set_rating(con, kind, key, payload.get("rating"),
                                     _label_for(cfg, kind, key))}


def h_ball(payload, con, cfg, user):
    kind, key = _entity(payload)
    return {"ball": crm.set_ball(con, kind, key, payload.get("ball", ""),
                                 _label_for(cfg, kind, key))}


def h_schedule(payload, con, cfg, user):
    kind, key = _entity(payload)
    on = payload.get("on_date", "")
    if on and not model.parse_iso(on):
        raise Error("next contact needs an ISO date (YYYY-MM-DD)")
    return {"next_contact_on": crm.set_next_contact(con, kind, key, on,
                                                    _label_for(cfg, kind, key))}


def h_note(payload, con, cfg, user):
    kind, key = _entity(payload)
    try:
        nid = crm.add_note(con, kind, key, payload.get("body", ""),
                           payload.get("pinned"), _label_for(cfg, kind, key),
                           author=user["email"])
    except ValueError as exc:
        raise Error(str(exc))
    return {"id": nid}


def h_note_edit(payload, con, cfg, user):
    nid = payload.get("id")
    if not nid:
        raise Error("note id required")
    crm.edit_note(con, nid, payload.get("body", ""))
    return {"id": nid}


def h_note_pin(payload, con, cfg, user):
    crm.set_note_pinned(con, payload.get("id"), payload.get("pinned"))
    return {"ok": True}


def h_checklist(payload, con, cfg, user):
    kind, key = _entity(payload)
    try:
        state = crm.set_item(con, kind, key, payload.get("item"),
                             payload.get("state"), payload.get("note", ""),
                             _label_for(cfg, kind, key))
    except ValueError as exc:
        raise Error(str(exc))
    return {"state": state}


def h_draft(payload, con, cfg, user):
    """Render a draft and report which blanks are still unfilled.

    Never blocks anything. The blanks are reported so the UI can warn at copy
    time; gating the *log* action on them would mean fighting a regex over a
    stale textarea after the mail has already gone, and the only way out would
    be typing filler -- which is precisely the behaviour the required blank
    exists to prevent.
    """
    kind, key = _entity(payload)
    variant = payload.get("variant") or "standard"
    if kind == "club":
        club = next((c for c in cfg.get("clubs", []) if c["key"] == key), None)
        if not club:
            raise Error("no such club", 404)
        text = (nudge.draft_near_term_club_email(club, cfg) if variant == "near_term"
                else nudge.draft_club_email(club, cfg))
    else:
        b = next((x for x in cfg.get("breeders", []) if x["key"] == key), None)
        if not b:
            raise Error("no such breeder", 404)
        text = nudge.draft_breeder_email(b, cfg)

    blanks = [line for line in text.split("\n") if "[" in line and "]" in line]
    return {"text": text, "blanks": blanks, "variant": variant}


def h_contact(payload, con, cfg, user):
    """Log that something was sent or received.

    Direction matters and was never written before: `db.contact` has had a
    `direction` column since the beginning and nothing ever wrote 'in'. Most of
    a real search is inbound -- a referral desk replying with three kennel
    names is the single most valuable event in it.
    """
    kind, key = _entity(payload)
    direction = payload.get("direction", "out")
    if direction not in ("out", "in"):
        raise Error("direction must be out or in")
    label = _label_for(cfg, kind, key)
    db.log_contact(con, key, kind, direction, payload.get("channel", "email"),
                   payload.get("summary", ""))

    state = crm.ensure_state(con, kind, key)
    if direction == "out":
        if state["stage"] == "new":
            crm.set_stage(con, kind, key, "contacted", label)
        crm.set_ball(con, kind, key, "them", label)
    else:
        crm.set_ball(con, kind, key, "us", label)
        if kind == "club" and state["stage"] in ("new", "contacted"):
            crm.set_stage(con, kind, key, "replied", label)
        elif kind == "breeder" and state["stage"] in ("new", "contacted"):
            crm.set_stage(con, kind, key, "talking", label)

    crm.log_event(con, f"contact_{direction}",  # noqa: E501
                  f"{label}: {'sent' if direction == 'out' else 'received'}"
                  + (f" — {payload.get('summary')}" if payload.get("summary") else ""),
                  kind, key)
    # The nudge for this entity has served its purpose.
    nudge.build_findings(con, cfg)
    return {"ok": True}


def h_dismiss(payload, con, cfg, user):
    fid = payload.get("id")
    if not fid:
        raise Error("finding id required")
    db.dismiss(con, fid)
    crm.log_event(con, "dismiss", f"dismissed finding {fid}")
    return {"ok": True}


def h_commitment(payload, con, cfg, user):
    try:
        cid = crm.add_commitment(con, payload.get("on_date"), payload.get("what", ""),
                                 payload.get("kind", ""), payload.get("key", ""),
                                 payload.get("note", ""))
    except ValueError as exc:
        raise Error(str(exc))
    return {"id": cid}


def h_commitment_done(payload, con, cfg, user):
    crm.complete_commitment(con, payload.get("id"), payload.get("done", 1))
    return {"ok": True}


def h_breeder(payload, con, cfg, user):
    """Add a breeder from the dashboard.

    This is the write that grows the search -- a referral desk replies with
    three kennel names and they need to land somewhere in under a minute.
    Leaving it CLI-only meant the one surface the user actually looks at
    refused to do the highest-value thing in the product.

    It writes to the database, not to config.yaml, so `yaml.safe_dump` never
    comes near the commented config. `provenance` is captured because "Rose at
    CRVGRC suggested I write to you" is the strongest opening line available.
    """
    from . import cli
    name = (payload.get("name") or "").strip()
    if not name:
        raise Error("a breeder needs a name")
    key = (payload.get("key") or name.lower().replace(" ", "-")[:24]).strip()
    if any(b["key"] == key for b in cfg.get("breeders", [])):
        raise Error(f"breeder {key} is already on the board")
    if any(c["key"] == key for c in cfg.get("clubs", [])):
        raise Error(f"{key} is already a club key; choose another")

    try:
        cli.append_breeder({
            "key": key, "name": name,
            "kennel_prefix": payload.get("prefix", ""),
            "location": payload.get("location", ""),
            "site": payload.get("site", ""),
            "watch_urls": [payload["site"]] if payload.get("site") else [],
            "email": payload.get("email", ""),
            "status": "researching", "line": payload.get("line", "unknown"),
            "notes": payload.get("notes", ""),
        })
    except ValueError as exc:
        raise Error(str(exc))
    crm.ensure_state(con, "breeder", key)
    provenance = payload.get("provenance", "")
    if provenance:
        crm.add_note(con, "breeder", key, f"Referred by {provenance}", pinned=1, label=name)
    crm.log_event(con, "breeder", f"added {name}"
                  + (f" (via {provenance})" if provenance else ""), "breeder", key)
    return {"key": key}


def h_dog(payload, con, cfg, user):
    fields = {k: payload.get(k) for k in crm.DOG_FIELDS if k in payload}
    try:
        if payload.get("id"):
            crm.update_dog(con, payload["id"], **fields)
            return {"id": payload["id"]}
        return {"id": crm.add_dog(con, **fields)}
    except ValueError as exc:
        raise Error(str(exc))


def h_litter(payload, con, cfg, user):
    if payload.get("id"):
        crm.update_litter(con, payload["id"], **{
            k: payload[k] for k in
            ("sire_id", "dam_id", "status", "bred_on", "due_on", "whelped_on",
             "pups_total", "pups_female", "pick_number", "note") if k in payload})
        return {"id": payload["id"]}
    key = payload.get("breeder_key")
    if not key:
        raise Error("a litter needs a breeder")
    return {"id": crm.add_litter(con, key, **payload)}


def h_sweep(payload, con, cfg, user):
    """Kick a sweep off as a detached process.

    Never on the request thread: a sweep is six polite fetches with a four
    second delay between them plus up to a 25 second timeout each, and it must
    not hold a worker or a database connection while it runs. The lock in
    `cli` is what stops it colliding with the cron run.
    """
    args = [sys.executable, "-m", "gw.cli", "run"]
    if payload.get("force"):
        args.append("--force")
    subprocess.Popen(args, cwd=str(ROOT), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    crm.log_event(con, "sweep", "sweep triggered from the dashboard")
    return {"started": True}


#: Routes a household member may use. Everything absent from this set is
#: owner-only — drafts because they interpolate a phone number, the household
#: paragraph and a child's age; `/api/sweep` because it fires a crawl at six
#: volunteer-run websites. Default-deny: a route added later is private until
#: it is deliberately listed here.
HOUSEHOLD_ROUTES = {
    "/api/stage", "/api/rating", "/api/ball", "/api/schedule",
    "/api/note", "/api/note/edit", "/api/note/pin", "/api/checklist",
    "/api/contact", "/api/dismiss", "/api/commitment", "/api/commitment/done",
    "/api/litter", "/api/dog", "/api/events",
}

ROUTES = {
    "/api/stage": h_stage,
    "/api/rating": h_rating,
    "/api/ball": h_ball,
    "/api/schedule": h_schedule,
    "/api/note": h_note,
    "/api/note/edit": h_note_edit,
    "/api/note/pin": h_note_pin,
    "/api/checklist": h_checklist,
    "/api/draft": h_draft,
    "/api/contact": h_contact,
    "/api/dismiss": h_dismiss,
    "/api/commitment": h_commitment,
    "/api/commitment/done": h_commitment_done,
    "/api/breeder": h_breeder,
    "/api/dog": h_dog,
    "/api/litter": h_litter,
    "/api/sweep": h_sweep,
}


# ---------------------------------------------------------------- http

def make_handler(cfg_loader, port):
    # Loopback always, plus any proxy hostname from config. Never a wildcard:
    # this stays a membership test because a prefix check would accept
    # `Host: 127.0.0.1:8420.evil.com`.
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    for host in (cfg_loader().get("access") or {}).get("public_hosts", []):
        allowed_hosts.add(str(host).strip().lower())

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0 is the default and gives no keep-alive, so every fetch on the
        # page would cost a fresh connection and a fresh thread.
        protocol_version = "HTTP/1.1"
        timeout = 15
        server_version = "golden-watch"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass                                   # the sweep log is the log

        # -------------------------------------------------- plumbing
        def _respond(self, status, body, content_type):
            payload = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, obj, status=200):
            self._respond(status, json.dumps(obj), "application/json; charset=utf-8")

        def _host_ok(self):
            return (self.headers.get("Host", "") or "").lower() in allowed_hosts

        def _who(self):
            """Identity, or a 403. Never an anonymous session."""
            user = identity.identify(self.headers, cfg_loader())
            if not user:
                raise Error("not authorised", 403)
            return user

        def _may(self, user, path):
            if user["role"] == "owner":
                return
            if path not in HOUSEHOLD_ROUTES:
                raise Error("not permitted", 403)

        def _read_payload(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise Error("body too large", 413)
            raw = self.rfile.read(length) if length else b"{}"
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype != "application/json":
                raise Error("expected application/json", 415)
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                raise Error("malformed JSON")
            if not isinstance(payload, dict):
                raise Error("expected a JSON object")
            return payload

        # -------------------------------------------------- routing
        def do_GET(self):
            if not self._host_ok():
                return self._json({"error": "bad host"}, 421)
            route = urlparse(self.path)
            try:
                if route.path == "/healthz":
                    return self._json({"ok": True})     # before auth: for the supervisor
                user = self._who()
                if route.path == "/":
                    return self._respond(200, self._render(user),
                                         "text/html; charset=utf-8")
                if route.path == "/api/events":
                    if self.headers.get("X-GW") != "1":
                        return self._json({"error": "missing X-GW"}, 403)
                    self._may(user, route.path)
                    q = parse_qs(route.query)
                    con = db.connect()
                    try:
                        return self._json({"events": crm.events(
                            con, kind=(q.get("kind") or [None])[0],
                            key=(q.get("key") or [None])[0],
                            limit=int((q.get("limit") or [200])[0]))})
                    finally:
                        con.close()
                return self._json({"error": "not found"}, 404)
            except Error as exc:
                return self._json({"error": str(exc)}, exc.status)
            except Exception:
                traceback.print_exc()
                return self._json({"error": "internal error"}, 500)

        def do_POST(self):
            if not self._host_ok():
                return self._json({"error": "bad host"}, 421)
            # The real CSRF control. A form POST cannot set this header, so a
            # cross-origin attempt is forced into a preflight it cannot pass.
            if self.headers.get("X-GW") != "1":
                return self._json({"error": "missing X-GW"}, 403)
            path = urlparse(self.path).path
            handler = ROUTES.get(path)
            if not handler:
                return self._json({"error": "not found"}, 404)
            con = None
            try:
                user = self._who()
                self._may(user, path)
                payload = self._read_payload()
                cfg = cfg_loader()
                con = db.connect()          # per request: sqlite is thread-bound
                crm.sync_entities(con, cfg)
                return self._json(handler(payload, con, cfg, user))
            except Error as exc:
                return self._json({"error": str(exc)}, exc.status)
            except Exception:
                traceback.print_exc()
                return self._json({"error": "internal error"}, 500)
            finally:
                if con:
                    con.close()

        def _render(self, user):
            cfg = cfg_loader()
            con = db.connect()
            try:
                crm.sync_entities(con, cfg)
                return dashboard.render(cfg, dashboard.collect(cfg, con), user)
            finally:
                con.close()

    return Handler


def serve(cfg_loader, port=8420, host="127.0.0.1"):
    handler = make_handler(cfg_loader, port)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def already_running(port):
    """Is the thing on this port one of us?

    Under launchd, a plain `KeepAlive: true` plus an occupied port is a silent
    infinite respawn loop: the agent restarts on every exit including
    EADDRINUSE, throttled to one relaunch per ten seconds, while the *older*
    copy happily answers the browser so everything looks fine. Exiting 0 when
    the squatter is already a golden-watch turns that into a no-op.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"http://127.0.0.1:{port}/healthz",
                                       headers={"Host": f"127.0.0.1:{port}"}),
                timeout=2) as res:
            return json.loads(res.read()).get("ok") is True
    except Exception:
        return False


def run(cfg_loader, port=8420):
    try:
        httpd = serve(cfg_loader, port)
    except OSError as exc:
        if getattr(exc, "errno", None) in (48, 98):      # EADDRINUSE
            if already_running(port):
                print(f"golden-watch is already serving on {port}")
                return None
            print(f"port {port} is taken by something else")
            raise SystemExit(1)
        raise
    url = f"http://127.0.0.1:{port}/"
    print(f"golden-watch command station on {url}")
    print("ctrl-c to stop")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\nstopping")
        httpd.shutdown()
    return httpd

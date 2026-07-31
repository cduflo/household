"""golden-watch command line.

  gw run                  one sweep: fetch, diff, score, alert, rebuild dashboard
  gw dash                 rebuild the dashboard without touching the network
  gw clubs                show referral contacts and who is overdue
  gw draft club <key>     print an email draft for a club referral volunteer
  gw draft breeder <key>  print an email draft for a breeder
  gw contacted <key>      log that you sent something, which resets the clock
  gw ofa <prefix>         look up a kennel prefix and audit the clearances
  gw add-breeder ...      append a breeder to config.yaml
"""
import argparse
import contextlib
import fcntl
import json
import sys
import time
from pathlib import Path

import yaml

from . import crm, db, fetch, signal, notify, nudge, dashboard, ofa, lines, publish

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
OUT = ROOT / "dashboard.html"
LOCKFILE = ROOT / ".sweep.lock"


@contextlib.contextmanager
def sweep_lock():
    """One sweep at a time, across processes.

    Both the cron job and the dashboard's "sweep now" button can start one, and
    they gate on the *stored* fetch timestamp -- so two overlapping sweeps read
    the same stale value and both fetch, doubling the request rate on
    volunteer-run shared hosting. They would also race on snapshot writes, so
    the later writer can overwrite a newer page with an older one.
    """
    handle = open(LOCKFILE, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        print("another sweep is already running; skipping")
        raise SystemExit(0)
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


LOCAL = ROOT / "owner.local.yaml"
CONTACTS = ROOT / "contacts.local.yaml"


def load_config():
    """config.yaml, overlaid with two untracked files.

    This repo is public, so nothing identifying anybody is tracked in it:

      owner.local.yaml     the household -- phone, a child's age, when the house
                           is occupied. Overlays the `owner:` section.
      contacts.local.yaml  the referral volunteers -- real names and personal
                           addresses harvested from club pages by people who
                           never agreed to be republished. Merged by club key.

    Without the overlays every club reads as having no contact route, which is
    the correct failure: the tool says it cannot write to anyone rather than
    quietly inventing an address.
    """
    with open(CONFIG) as fh:
        cfg = yaml.safe_load(fh)

    if LOCAL.exists():
        with open(LOCAL) as fh:
            local = yaml.safe_load(fh) or {}
        for section, values in local.items():
            if isinstance(values, dict):
                cfg.setdefault(section, {}).update(values)
            else:
                cfg[section] = values

    if CONTACTS.exists():
        with open(CONTACTS) as fh:
            overlay = (yaml.safe_load(fh) or {}).get("clubs", {}) or {}
        by_key = {c["key"]: c for c in cfg.get("clubs", [])}
        for key, fields in overlay.items():
            if key in by_key:
                by_key[key].update(fields)
    return cfg


def append_breeder(entry):
    """Append to config.yaml as raw text.

    Deliberately not a yaml round-trip. safe_dump would silently strip every
    comment in the file, and the comments here carry the reasoning -- why the
    clubs are a cadence and not a scrape target, what the line tags mean. Losing
    them the first time you add a breeder would be a bad trade.
    """
    # Guard at the point of writing, not only at the caller. The caller checks
    # against a config it loaded earlier; this checks the file about to be
    # appended to, which is what actually prevents a duplicate key.
    if any(line.strip() == f"- key: {entry['key']}"
           for line in CONFIG.read_text().splitlines()):
        raise ValueError(f"{entry['key']} is already in config.yaml")

    block = ["  - key: %s" % entry["key"]]
    for k in ("name", "kennel_prefix", "location", "site", "email", "status", "line"):
        block.append('    %s: "%s"' % (k, str(entry.get(k, "")).replace('"', "'")))
    if entry.get("watch_urls"):
        block.append("    watch_urls:")
        block.extend("      - %s" % u for u in entry["watch_urls"])
    if entry.get("notes"):
        block.append('    notes: "%s"' % entry["notes"].replace('"', "'"))
    with open(CONFIG, "a") as fh:
        fh.write("\n" + "\n".join(block) + "\n")


# ---------------------------------------------------------------- run

def cmd_run(args):
    with sweep_lock():
        _sweep(args)


def _sweep(args):
    cfg = load_config()
    con = db.connect()
    crm.sync_entities(con, cfg)
    w = cfg.get("watcher", {})
    ua = w.get("user_agent", "golden-watch/1.0")
    delay = w.get("request_delay_seconds", 4)
    min_gap = w.get("min_interval_hours", 12) * 3600

    checked = changed = errors = 0
    new_ids = []

    for target in cfg.get("watch", []):
        prev = db.get_snapshot(con, target["key"])
        if prev and not args.force and (time.time() - prev["fetched_at"]) < min_gap:
            continue

        text, status, error = fetch.fetch(target["url"], ua)
        checked += 1
        fetch.polite_sleep(delay)

        if error:
            errors += 1
            db.put_snapshot(con, target["key"], target["url"],
                            prev["text"] if prev else "", prev["digest"] if prev else "",
                            status, error)
            print(f"  ! {target['label']}: {error}")
            continue

        dig = fetch.digest(text)
        if prev and prev["digest"] == dig:
            print(f"  = {target['label']}")
            db.put_snapshot(con, target["key"], target["url"], text, dig, status, None)
            continue

        added = fetch.added_lines(prev["text"] if prev else "", text)
        db.put_snapshot(con, target["key"], target["url"], text, dig, status, None)

        if not prev:
            print(f"  + {target['label']}: baseline stored")
            continue

        changed += 1
        score, reasons, evidence = signal.score_lines(added, kind=target.get("type", "litter"))
        if score <= 0:
            print(f"  ~ {target['label']}: changed, nothing that looks like news")
            continue

        kind = "event" if target.get("type") == "events" else (
            "referral" if target.get("type") == "referral" else "litter")
        excerpt = f"[{', '.join(reasons)}] " + signal.summarize(evidence)
        fid = db.add_finding(con, target["key"], target["label"], target["url"],
                             kind, score, excerpt)
        new_ids.append(fid)
        print(f"  * {target['label']}: score {score} ({', '.join(reasons)})")

    # Breeder sites get the same treatment, with a louder default kind.
    for b in cfg.get("breeders", []):
        for i, url in enumerate(b.get("watch_urls", []) or []):
            key = f"breeder:{b['key']}:{i}"
            prev = db.get_snapshot(con, key)
            if prev and not args.force and (time.time() - prev["fetched_at"]) < min_gap:
                continue
            text, status, error = fetch.fetch(url, ua)
            checked += 1
            fetch.polite_sleep(delay)
            if error:
                errors += 1
                print(f"  ! {b['name']}: {error}")
                continue
            dig = fetch.digest(text)
            if prev and prev["digest"] == dig:
                db.put_snapshot(con, key, url, text, dig, status, None)
                continue
            added = fetch.added_lines(prev["text"] if prev else "", text)
            db.put_snapshot(con, key, url, text, dig, status, None)
            if not prev:
                print(f"  + {b['name']}: baseline stored")
                continue
            changed += 1
            score, reasons, evidence = signal.score_lines(added, kind="litter")
            if score <= 0:
                continue
            fid = db.add_finding(con, key, b["name"], url, "litter", score,
                                 f"[{', '.join(reasons)}] " + signal.summarize(evidence))
            new_ids.append(fid)
            print(f"  * {b['name']}: score {score} ({', '.join(reasons)})")

    nudge.build_findings(con, cfg)
    # Keep the browser's draft skeletons in step with config and the target date.
    publish.publish(con, cfg)

    pending = db.unnotified(con)
    sent = notify.dispatch(cfg, pending) if not args.no_notify else []
    if sent:
        db.mark_notified(con, sent)

    db.log_run(con, checked, changed, len(sent), errors)
    build_dashboard(cfg, con)
    print(f"\n{checked} checked · {changed} changed · {len(sent)} alerted · {errors} errors")
    print(f"dashboard: {OUT}")


# ---------------------------------------------------------------- dashboard

def build_dashboard(cfg, con):
    """Write the offline copy. The live server renders the same thing without
    touching the filesystem -- `collect` and `render` are pure for that reason."""
    crm.sync_entities(con, cfg)
    OUT.write_text(dashboard.render(cfg, dashboard.collect(cfg, con)), encoding="utf-8")
    return OUT


def cmd_dash(args):
    cfg = load_config()
    con = db.connect()
    print(build_dashboard(cfg, con))


# ---------------------------------------------------------------- clubs / drafts

def cmd_clubs(args):
    cfg = load_config()
    con = db.connect()
    due = {d["club"]["key"]: d["reason"] for d in nudge.due_clubs(con, cfg)}
    for c in cfg.get("clubs", []):
        last = db.last_contact(con, c["key"])
        when = time.strftime("%Y-%m-%d", time.localtime(last["at"])) if last else "never"
        mark = "DUE " if c["key"] in due else "    "
        print(f"{mark}{c['key']:<10} {c['name']:<34} {c.get('referral_email') or c.get('method'):<34} last: {when}")


def cmd_draft(args):
    cfg = load_config()
    if args.what == "club":
        club = next((c for c in cfg["clubs"] if c["key"] == args.key), None)
        if not club:
            sys.exit(f"No club with key {args.key}")
        print(nudge.draft_near_term_club_email(club, cfg) if args.now
              else nudge.draft_club_email(club, cfg))
    else:
        b = next((x for x in cfg["breeders"] if x["key"] == args.key), None)
        if not b:
            sys.exit(f"No breeder with key {args.key}")
        print(nudge.draft_breeder_email(b, cfg))


def cmd_contacted(args):
    cfg = load_config()
    con = db.connect()
    ttype = "club" if any(c["key"] == args.key for c in cfg.get("clubs", [])) else "breeder"
    db.log_contact(con, args.key, ttype, "out", args.channel, args.note or "")
    print(f"Logged {args.channel} to {args.key}. Clock reset.")
    build_dashboard(cfg, con)


# ---------------------------------------------------------------- OFA

def cmd_ofa(args):
    cfg = load_config()
    con = db.connect()
    ua = cfg.get("watcher", {}).get("user_agent", "golden-watch/1.0")

    if args.text:
        clearances = ofa.parse_clearances(Path(args.text).read_text()
                                          if Path(args.text).exists() else args.text)
    else:
        result = ofa.lookup(args.prefix, fetch.fetch, ua)
        db.put_ofa(con, args.prefix, result)
        print(result["note"])
        print(result["url"])
        if not result["rows"]:
            return
        clearances = result["rows"][0]

    print(json.dumps(clearances, indent=2))
    verdict = ofa.audit(clearances)
    print(f"\n{verdict['score']}/4 clearances on file"
          f"{' — complete' if verdict['complete'] else ''}")
    for flag in verdict["flags"]:
        print(f"  - {flag}")


# ---------------------------------------------------------------- line

def cmd_line(args):
    cfg = load_config()
    ua = cfg.get("watcher", {}).get("user_agent", "golden-watch/1.0")

    if args.url:
        text, status, error = fetch.fetch(args.url, ua)
        if error:
            sys.exit(f"Could not read that page: {error}")
    elif args.text:
        text = args.text
    else:
        sys.exit("Give me --url or --text.")

    result = lines.classify(text)
    want = cfg.get("preferences", {}).get("line", "any")
    match = lines.matches_preference(result, want)

    print(f"Line: {result['line'].upper()}")
    print(result["note"])
    if result["show_titles"]:
        print("  show:    " + ", ".join(f"{t} ({lines.SHOW_TITLES[t]})" for t in result["show_titles"]))
    if result["field_titles"]:
        print("  field:   " + ", ".join(f"{t} ({lines.FIELD_TITLES[t]})" for t in result["field_titles"]))
    if result["neutral_titles"]:
        print("  neutral: " + ", ".join(result["neutral_titles"]))

    verdict = {True: "matches", False: "does NOT match", None: "unresolved against"}[match]
    print(f"\nThis {verdict} your preference for {want} lines.")

    for c in result["cautions"]:
        print(f"\n  ! {c}")


# ---------------------------------------------------------------- add

def cmd_add_breeder(args):
    cfg = load_config()
    key = args.key or args.name.lower().replace(" ", "-")[:24]
    if any(b["key"] == key for b in cfg.get("breeders", [])):
        sys.exit(f"Breeder {key} already on the board.")
    cfg.setdefault("breeders", []).append({
        "key": key,
        "name": args.name,
        "kennel_prefix": args.prefix or "",
        "location": args.location or "",
        "site": args.site or "",
        "watch_urls": [args.site] if args.site else [],
        "email": args.email or "",
        "status": "researching",
        "line": args.line or "unknown",
        "notes": args.note or "",
    })
    entry = cfg["breeders"][-1]
    cfg["breeders"].pop()
    append_breeder(entry)
    print(f"Added {args.name} as {key}.")
    if entry.get("line") == "unknown":
        print("Line is unset. Run `gw line --url <their pedigree page>` to classify it.")


def cmd_serve(args):
    from . import serve
    if args.open:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    serve.run(load_config, args.port)


def cmd_dismiss(args):
    con = db.connect()
    if db.dismiss(con, args.id):
        crm.log_event(con, "dismiss", f"dismissed finding {args.id}")
        print(f"Dismissed {args.id}.")
    else:
        sys.exit(f"No finding {args.id}.")


def main():
    p = argparse.ArgumentParser(prog="gw", description="Golden retriever search watcher")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="one sweep")
    r.add_argument("--force", action="store_true", help="ignore the minimum interval")
    r.add_argument("--no-notify", action="store_true")
    r.set_defaults(func=cmd_run)

    sub.add_parser("dash", help="rebuild dashboard").set_defaults(func=cmd_dash)
    sub.add_parser("clubs", help="referral contacts").set_defaults(func=cmd_clubs)

    d = sub.add_parser("draft", help="print an email draft")
    d.add_argument("what", choices=["club", "breeder"])
    d.add_argument("key")
    d.add_argument("--now", action="store_true",
                   help="near-term ask: is there an unplaced puppy already on the ground")
    d.set_defaults(func=cmd_draft)

    c = sub.add_parser("contacted", help="log outbound contact")
    c.add_argument("key")
    c.add_argument("--channel", default="email", choices=["email", "form", "phone", "in_person"])
    c.add_argument("--note", default="")
    c.set_defaults(func=cmd_contacted)

    o = sub.add_parser("ofa", help="look up and audit clearances")
    o.add_argument("prefix", nargs="?", default="")
    o.add_argument("--text", help="audit a pasted claim or a file instead of searching")
    o.set_defaults(func=cmd_ofa)

    a = sub.add_parser("add-breeder")
    a.add_argument("name")
    a.add_argument("--key")
    a.add_argument("--prefix", help="registered kennel prefix, for OFA")
    a.add_argument("--site")
    a.add_argument("--email")
    a.add_argument("--location")
    a.add_argument("--note")
    a.add_argument("--line", choices=["show", "field", "dual", "unknown"])
    a.set_defaults(func=cmd_add_breeder)

    ln = sub.add_parser("line", help="classify a breeder as show or field from titles")
    ln.add_argument("--url", help="a pedigree or 'our dogs' page to read")
    ln.add_argument("--text", help="paste titles or a pedigree instead")
    ln.set_defaults(func=cmd_line)

    sv = sub.add_parser("serve", help="run the command station")
    sv.add_argument("--port", type=int, default=8420)
    sv.add_argument("--open", action="store_true", help="open a browser at it")
    sv.set_defaults(func=cmd_serve)

    ds = sub.add_parser("dismiss", help="acknowledge a finding")
    ds.add_argument("id", type=int)
    ds.set_defaults(func=cmd_dismiss)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

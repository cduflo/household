"""The command station.

`collect()` gathers, `render()` renders, and neither writes a file. That split
matters: the old `build_dashboard` wrote `dashboard.html` as a side effect of
reading, so serving a page from it would rewrite the file on every load.

Visual direction is the paperwork this search actually runs on: OFA certificates
and club registry cards laid out on a dark desk. Buff card stock, registry ink,
a rubber-stamp red for anything unverified.

The signature element is the clearance strip, and it hangs off a *litter*, not a
kennel. Four stamped cells for hips, elbows, eyes and heart on the actual sire
and dam of an actual breeding, because that pairing is the thing you are
choosing and a kennel-level average is not a fact about any puppy.

Fonts are the system stack on purpose. The page renders a phone number and a
child's age, and the old Google Fonts link handed an IP, a user agent and a
referrer to a third party on every load.
"""
import html
import json
import time
from datetime import date, datetime

from . import crm, db, model, nudge, ofa

CSS = """
:root{
  --ink:#101B24; --ink-2:#18262F; --stock:#DFD9C8; --stock-hi:#EFEADC;
  --rule:#A99F84; --stamp:#9E3223; --clear:#2F6B45; --pending:#9C6B0F;
  --muted:#6E6650; --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--ink);
  background-image:
    radial-gradient(ellipse at 12% -10%, rgba(255,255,255,.06), transparent 55%),
    repeating-linear-gradient(0deg, rgba(255,255,255,.014) 0 1px, transparent 1px 4px);
  color:var(--stock); font-family:var(--sans); font-size:15px; line-height:1.5;
  padding:clamp(14px,3vw,40px);
}
.wrap{max-width:1240px;margin:0 auto}

.masthead{border-bottom:2px solid var(--rule);padding-bottom:14px;margin-bottom:8px}
.mast-title{font-weight:800;font-size:clamp(28px,5vw,46px);line-height:.98;
  letter-spacing:-.02em;text-transform:uppercase;margin:0;color:var(--stock-hi)}
.mast-sub{font-family:var(--mono);font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--rule);margin-top:8px;
  display:flex;flex-wrap:wrap;gap:4px 20px}

/* the scoreboard that actually measures the search */
.score{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 6px}
.score-cell{border:1px solid var(--rule);border-radius:2px;padding:8px 14px;
  background:rgba(223,217,200,.05);min-width:104px}
.score-n{font-size:26px;font-weight:800;color:var(--stock-hi);line-height:1}
.score-k{font-family:var(--mono);font-size:9.5px;letter-spacing:.13em;
  text-transform:uppercase;color:var(--rule);margin-top:4px;display:block}
.score-cell.zero .score-n{color:var(--stamp)}

.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.15em;
  text-transform:uppercase;color:var(--rule);display:flex;align-items:baseline;
  gap:12px;margin:30px 0 12px}
.eyebrow::after{content:"";flex:1;height:1px;background:var(--rule);opacity:.42}
.eyebrow .count{color:var(--stock);font-size:11px}

.card{background:var(--stock);color:var(--ink);border-radius:2px;
  padding:14px 16px;margin-bottom:10px;border-left:4px solid var(--rule);
  box-shadow:0 1px 0 rgba(0,0,0,.5),0 10px 26px -18px rgba(0,0,0,.9)}
.card.hot{border-left-color:var(--stamp)}
.card.warm{border-left-color:var(--pending)}
.card.cool{border-left-color:var(--clear)}
.card-top{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;
  justify-content:space-between}
.card-name{font-weight:800;font-size:19px;letter-spacing:-.01em;margin:0}
.card-meta{font-family:var(--mono);font-size:10.5px;letter-spacing:.05em;
  color:var(--muted);text-transform:uppercase}
.card-body{margin:8px 0 0;font-size:14px;color:#2A2A22}
.card-body a{color:var(--stamp)}
.card-note{margin-top:8px;padding-top:8px;border-top:1px dashed var(--rule);
  font-family:var(--mono);font-size:11px;color:var(--muted);word-break:break-word}

/* clearance strip -- per pairing, never per kennel */
.strip{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.cell{min-width:84px;padding:5px 8px;border:1.5px solid var(--rule);
  border-radius:1px;background:rgba(255,255,255,.34)}
.cell-k{font-family:var(--mono);font-size:9px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--muted);display:block}
.cell-v{font-weight:800;font-size:13px;display:block;margin-top:1px}
.cell.pass{border-color:var(--clear);background:rgba(47,107,69,.14)}
.cell.pass .cell-v{color:var(--clear)}
.cell.fail{border-style:dashed;border-color:var(--stamp);background:transparent}
.cell.fail .cell-v{color:var(--stamp)}
.cell.waiting{border-style:dotted;border-color:var(--pending)}
.cell.waiting .cell-v{color:var(--pending)}
.cell.todo{border-style:dotted}
.cell.todo .cell-v{color:var(--muted)}

.badge{display:inline-block;margin:0 5px 4px 0;padding:2px 7px;border-radius:1px;
  font-family:var(--mono);font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  border:1px solid var(--rule);color:var(--muted)}
.badge.show{border-color:var(--clear);color:var(--clear)}
.badge.field{border-color:var(--pending);color:var(--pending)}
.badge.ball-us{border-color:var(--stamp);color:var(--stamp);font-weight:700}
.badge.ball-them{border-color:var(--muted)}

.stars{display:inline-flex;gap:1px;vertical-align:middle}
.star{cursor:pointer;font-size:15px;line-height:1;color:var(--rule);
  background:none;border:0;padding:0 1px}
.star.on{color:var(--pending)}

.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:10px}
select,input[type=text],input[type=date],textarea{
  font-family:var(--sans);font-size:13px;padding:5px 7px;border:1px solid var(--rule);
  border-radius:2px;background:rgba(255,255,255,.5);color:var(--ink)}
textarea{width:100%;font-family:var(--mono);font-size:12px;line-height:1.45;min-height:230px}
button{font-family:var(--sans);font-size:12px;font-weight:600;padding:5px 11px;
  border:1px solid var(--ink);border-radius:2px;background:var(--ink);color:var(--stock);
  cursor:pointer}
button.ghost{background:transparent;color:var(--ink)}
button:hover{opacity:.85}
button:disabled{opacity:.4;cursor:not-allowed}

details{margin-top:10px;border-top:1px dashed var(--rule);padding-top:8px}
details summary{cursor:pointer;font-family:var(--mono);font-size:10.5px;
  letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
details[open] summary{margin-bottom:8px;color:var(--ink)}

.check{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px}
.check select{font-size:11px;padding:2px 4px;min-width:78px}
.check .lbl{flex:1}
.check.st-fail .lbl{color:var(--stamp);font-weight:600}
.check.st-pass .lbl{color:var(--clear)}
.check.st-waiting .lbl{color:var(--pending)}

.notes{margin:0;padding:0;list-style:none}
.notes li{padding:6px 0;border-bottom:1px dotted var(--rule);font-size:13px}
.notes li.pin{background:rgba(156,107,15,.09);padding-left:6px;
  border-left:2px solid var(--pending)}
.notes time{font-family:var(--mono);font-size:10px;color:var(--muted);
  display:block;margin-top:2px}

.plan{display:flex;flex-wrap:wrap;gap:8px}
.plan-item{border:1px solid var(--pending);border-radius:2px;padding:8px 12px;
  background:rgba(156,107,15,.12);min-width:150px}
.plan-d{font-weight:800;font-size:17px;color:var(--stock-hi)}
.plan-w{font-size:12.5px;color:var(--stock)}
.plan-item.soon{border-color:var(--stamp);background:rgba(158,50,35,.18)}

.log{max-height:340px;overflow-y:auto;border:1px solid var(--rule);border-radius:2px}
.log-row{display:flex;gap:10px;padding:6px 10px;border-bottom:1px dotted rgba(169,159,132,.35);
  font-size:12.5px;align-items:baseline}
.log-row:last-child{border-bottom:0}
.log-when{font-family:var(--mono);font-size:10px;color:var(--rule);white-space:nowrap;min-width:88px}
.log-verb{font-family:var(--mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);min-width:74px}

.empty{border:1px dashed var(--rule);border-radius:2px;padding:16px;color:var(--rule);font-size:14px}
.empty b{color:var(--stock);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:10px}
.foot{margin-top:40px;padding-top:12px;border-top:1px solid var(--rule);
  font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--rule)}
.toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);
  background:var(--stock);color:var(--ink);padding:9px 16px;border-radius:2px;
  font-size:13px;font-weight:600;box-shadow:0 8px 30px -8px #000;opacity:0;
  transition:opacity .18s;pointer-events:none;z-index:99}
.toast.on{opacity:1}
.warn{background:rgba(158,50,35,.12);border:1px solid var(--stamp);color:#6d2318;
  padding:7px 10px;border-radius:2px;font-size:12px;margin-top:8px}
a{color:inherit}
:focus-visible{outline:2px solid var(--pending);outline-offset:2px}
@media (max-width:620px){.grid{grid-template-columns:1fr}}
"""


def e(e_):
    return html.escape(str(e_ if e_ is not None else ""), quote=True)


SAFE_SCHEMES = ("http://", "https://", "mailto:")


def safe_url(url):
    """A `javascript:` URL pasted out of a referral reply must not become a
    clickable script link."""
    u = str(url or "").strip()
    return u if u.lower().startswith(SAFE_SCHEMES) else ""


def _ago(ts):
    if not ts:
        return "never"
    d = (time.time() - ts) / 86400
    if d < 1:
        return f"{int(d * 24)}h ago"
    if d < 60:
        return f"{int(d)}d ago"
    return f"{int(d / 30)}mo ago"


# ---------------------------------------------------------------- collect

def collect(cfg, con, today=None):
    """Everything the page needs, as plain data. Writes nothing."""
    today = today or date.today()
    states = crm.all_states(con)
    notes = crm.all_notes(con)
    checks = crm.all_checklists(con)

    breeders = []
    for b in cfg.get("breeders", []):
        key = b["key"]
        state = states.get(("breeder", key), {"stage": "new", "rating": 0, "ball": "",
                                              "next_contact_on": ""})
        rows = checks.get(("breeder", key), {})
        done, applicable, failed = model.checklist_progress(rows, "breeder", state["stage"])
        best = crm.best_litter_audit(con, key, today)
        last = db.last_contact(con, key)
        breeders.append({
            "cfg": b, "state": state, "checks": rows,
            "items": model.checklist_for("breeder", state["stage"]),
            "progress": (done, applicable), "failed": failed,
            "litters": crm.litters(con, key),
            "best": best, "notes": notes.get(("breeder", key), []),
            "last_contact": last["at"] if last else None,
        })

    due_club_keys = {d["club"]["key"] for d in nudge.due_clubs(con, cfg, today)}
    clubs = []
    for c in cfg.get("clubs", []):
        if c.get("method") == "reference":
            continue
        key = c["key"]
        state = states.get(("club", key), {"stage": "new", "rating": 0, "ball": "",
                                           "next_contact_on": ""})
        rows = checks.get(("club", key), {})
        done, applicable, failed = model.checklist_progress(rows, "club")
        last = db.last_contact(con, key)
        clubs.append({
            "cfg": c, "state": state, "checks": rows,
            "items": model.checklist_for("club"),
            "progress": (done, applicable), "failed": failed,
            "notes": notes.get(("club", key), []),
            "last_contact": last["at"] if last else None,
            "due": key in due_club_keys,
            "routable": nudge.has_contact_route(c),
        })

    counts = {r["direction"]: r["n"] for r in con.execute(
        "SELECT direction, COUNT(*) AS n FROM contact GROUP BY direction")}
    waitlists = sum(1 for b in breeders
                    if b["state"]["stage"] in ("waitlist", "deposit", "placed"))
    events_done = con.execute(
        "SELECT COUNT(*) AS n FROM commitment WHERE done = 1").fetchone()["n"]

    return {
        "breeders": breeders,
        "clubs": clubs,
        "unroutable": nudge.unroutable_clubs(cfg),
        "findings": db.recent_findings(con),
        "run": db.last_run(con),
        "plan": model.upcoming(crm.commitments(con), 60, today),
        "events": crm.events(con, limit=120),
        "dogs": crm.dogs(con),
        "target": nudge.effective_target(cfg, today),
        "scoreboard": {
            "sent": counts.get("out", 0), "replies": counts.get("in", 0),
            "events": events_done, "waitlists": waitlists,
        },
    }


# ---------------------------------------------------------------- pieces

def scoreboard(data):
    """The four numbers that measure the search.

    Deliberately replaces the sweep's own counters (pages checked, pages
    changed). Those measure the machine. These measure whether anything is
    actually happening, and three of them being zero is the most useful thing
    this page can tell you.
    """
    s = data["scoreboard"]
    cells = [("Emails sent", s["sent"]), ("Replies", s["replies"]),
             ("Events attended", s["events"]), ("Waitlists", s["waitlists"])]
    out = []
    for label, n in cells:
        out.append(f'<div class="score-cell{" zero" if not n else ""}">'
                   f'<span class="score-n">{n}</span>'
                   f'<span class="score-k">{e(label)}</span></div>')
    return f'<div class="score">{"".join(out)}</div>'


def plan_strip(data):
    if not data["plan"]:
        return ('<div class="empty">No dates on the calendar. '
                'Club events are the back door — referral volunteers rank people '
                'they have met, and that is the one thing a sweep cannot do for you.'
                '</div>')
    out = []
    for c in data["plan"]:
        klass = "plan-item soon" if c["days"] <= 14 else "plan-item"
        when = "today" if c["days"] == 0 else f'in {c["days"]}d'
        out.append(f'<div class="{klass}"><div class="plan-d">{e(when)}</div>'
                   f'<div class="plan-w">{e(c["what"])}</div>'
                   f'<div class="card-meta">{e(c["on_date"])}</div></div>')
    return f'<div class="plan">{"".join(out)}</div>'


def clearance_strip(best):
    """Four cells for the actual sire and dam of one breeding."""
    if not best:
        return ('<div class="card-note">No litter on file. Clearances are facts '
                'about two specific dogs, so there is nothing to audit until you '
                'know the pairing.</div>')
    litter, audit = best
    cells = []
    for label, trait in (("Hips", "hips"), ("Elbows", "elbows"),
                         ("Eyes", "eyes"), ("Heart", "heart")):
        states = [audit[r][trait][0] for r in ("sire", "dam") if audit.get(r)]
        if not states:
            state, text = "todo", "—"
        elif all(s == "pass" for s in states) and len(states) == 2:
            state, text = "pass", "Both"
        elif "fail" in states:
            state, text = "fail", "Problem"
        elif "waiting" in states:
            state, text = "waiting", "Unverified"
        else:
            state, text = "todo", "Partial"
        cells.append(f'<div class="cell {state}"><span class="cell-k">{e(label)}</span>'
                     f'<span class="cell-v">{e(text)}</span></div>')
    flags = ""
    if audit["flags"]:
        items = "".join(f"<li>{e(f)}</li>" for f in audit["flags"][:6])
        flags = f'<ul class="card-note" style="margin-left:14px">{items}</ul>'
    when = litter.get("due_on") or litter.get("whelped_on") or litter.get("bred_on") or "timing unknown"
    return (f'<div class="card-meta" style="margin-top:9px">Best pairing on file · '
            f'{e(litter["status"])} · {e(when)}</div>'
            f'<div class="strip">{"".join(cells)}</div>{flags}')


def stars(kind, key, rating):
    out = []
    for i in range(1, 6):
        on = " on" if i <= (rating or 0) else ""
        out.append(f'<button class="star{on}" data-kind="{e(kind)}" data-key="{e(key)}" '
                   f'data-rate="{i}" title="{e(model.RATING_LABELS[i])}">★</button>')
    return f'<span class="stars">{"".join(out)}</span>'


def stage_select(kind, key, stage):
    opts = "".join(
        f'<option value="{e(s)}"{" selected" if s == stage else ""}>'
        f'{e(model.STAGE_LABELS.get(s, s))}</option>'
        for s in model.stages_for(kind))
    return (f'<select data-stage data-kind="{e(kind)}" data-key="{e(key)}">{opts}</select>')


def checklist_block(kind, key, items, rows):
    out = []
    for item, label in items:
        state = rows.get(item, "todo")
        opts = "".join(f'<option value="{s}"{" selected" if s == state else ""}>{s}</option>'
                       for s in model.ITEM_STATES)
        out.append(
            f'<div class="check st-{e(state)}"><span class="lbl">{e(label)}</span>'
            f'<select data-check data-kind="{e(kind)}" data-key="{e(key)}" '
            f'data-item="{e(item)}">{opts}</select></div>')
    return "".join(out)


def notes_block(kind, key, notes):
    lis = []
    for n in notes:
        pin = " pin" if n["pinned"] else ""
        when = datetime.fromtimestamp(n["at"]).strftime("%d %b %Y %H:%M")
        lis.append(f'<li class="{pin.strip() or ""}">{e(n["body"])}'
                   f'<time>{e(when)}</time></li>')
    listing = f'<ul class="notes">{"".join(lis)}</ul>' if lis else ""
    return (listing +
            f'<div class="row"><input type="text" data-note-input '
            f'data-kind="{e(kind)}" data-key="{e(key)}" placeholder="Add a note — '
            f'what they said, what you promised" style="flex:1;min-width:200px">'
            f'<button data-note-save data-kind="{e(kind)}" data-key="{e(key)}">Add</button>'
            f'<button class="ghost" data-note-save data-kind="{e(kind)}" '
            f'data-key="{e(key)}" data-pin="1">Add pinned</button></div>')


def entity_actions(kind, key, state, variants, owner=True):
    """Controls for one entity.

    The draft button is omitted entirely for a household session rather than
    hidden — a draft interpolates the household paragraph, a phone number and a
    child's age, so it must not be in the response at all. Logging what was sent
    and what came back stays shared: that is the collaboration.
    """
    ball = state.get("ball") or ""
    ball_badge = ""
    if ball == "us":
        ball_badge = '<span class="badge ball-us">Your move</span>'
    elif ball == "them":
        ball_badge = '<span class="badge ball-them">Waiting on them</span>'
    variant_sel = ""
    if owner and len(variants) > 1:
        opts = "".join(f'<option value="{v}">{lbl}</option>' for v, lbl in variants)
        variant_sel = (f'<select data-variant data-key="{e(key)}">{opts}</select>')
    nxt = state.get("next_contact_on") or ""
    return (
        f'<div class="row">{ball_badge}{variant_sel}'
        + (f'<button data-draft data-kind="{e(kind)}" data-key="{e(key)}">Draft email</button>'
           if owner else '')
        + f'<button class="ghost" data-sent data-kind="{e(kind)}" data-key="{e(key)}">'
        f'Log sent</button>'
        f'<button class="ghost" data-reply data-kind="{e(kind)}" data-key="{e(key)}">'
        f'Log reply</button>'
        f'</div>'
        f'<div class="row"><span class="card-meta">Check back on</span>'
        f'<input type="date" value="{e(nxt)}" data-schedule data-kind="{e(kind)}" '
        f'data-key="{e(key)}">'
        f'<span class="card-meta">overrides the interval</span></div>'
        f'<div data-draftbox="{e(kind)}:{e(key)}"></div>')


def breeder_card(b, owner=True):
    cfgb, state = b["cfg"], b["state"]
    done, applicable = b["progress"]
    key, name = cfgb["key"], cfgb.get("name", cfgb["key"])
    tone = "hot" if b["failed"] else (
        "cool" if state["stage"] in ("waitlist", "deposit", "placed") else
        ("warm" if state["ball"] == "us" else ""))
    line = (cfgb.get("line") or "unknown").lower()
    line_badge = (f'<span class="badge {e(line)}">'
                  f'{e({"show": "Show lines", "field": "Field lines", "dual": "Dual"}.get(line, "Line unknown"))}'
                  f'</span>')
    pinned = next((n for n in b["notes"] if n["pinned"]), None)
    pinned_html = (f'<div class="card-note" style="border-left:2px solid var(--pending);'
                   f'padding-left:8px;border-top:0">{e(pinned["body"])}</div>'
                   if pinned else "")
    site = safe_url(cfgb.get("site"))
    site_html = f'<div class="card-note"><a href="{e(site)}">{e(site)}</a></div>' if site else ""
    warn = ('<div class="warn">A screening check came back <b>fail</b>. '
            'That is a finding, not a chore.</div>') if b["failed"] else ""

    return f"""<article class="card {tone}">
  <div class="card-top">
    <h3 class="card-name">{e(name)}</h3>
    <span class="card-meta">{stars("breeder", key, state["rating"])} · contact {e(_ago(b["last_contact"]))}</span>
  </div>
  <p class="card-body">{line_badge}{e(cfgb.get("location") or "")}</p>
  {pinned_html}
  {clearance_strip(b["best"])}
  {warn}
  <div class="row">{stage_select("breeder", key, state["stage"])}
    <span class="card-meta">Checklist {done}/{applicable}</span></div>
  {entity_actions("breeder", key, state, [("standard", "Introduction")], owner)}
  <details>
    <summary>Checklist, notes and litters</summary>
    {checklist_block("breeder", key, b["items"], b["checks"])}
    <div class="card-note" style="border-top:0;padding-top:10px">Notes</div>
    {notes_block("breeder", key, b["notes"])}
    <div class="card-note" style="border-top:0;padding-top:10px">
      Litters — clearances are audited on the sire and dam of a specific breeding
    </div>
    {litters_block(b)}
  </details>
  {site_html}
</article>"""


def litters_block(b):
    rows = []
    for lit in b["litters"]:
        when = lit.get("due_on") or lit.get("whelped_on") or lit.get("bred_on") or "—"
        pick = f' · pick #{lit["pick_number"]}' if lit.get("pick_number") else ""
        rows.append(f'<div class="check"><span class="lbl">{e(lit["status"])} · '
                    f'{e(when)}{e(pick)}</span></div>')
    listing = "".join(rows) or '<div class="card-meta">None recorded.</div>'
    return (listing +
            f'<div class="row">'
            f'<button class="ghost" data-litter data-key="{e(b["cfg"]["key"])}">'
            f'Add a litter</button></div>')


def club_card(c, owner=True):
    cfgc, state = c["cfg"], c["state"]
    done, applicable = c["progress"]
    key, name = cfgc["key"], cfgc.get("name", cfgc["key"])
    tone = "warm" if c["due"] else ("cool" if state["stage"] in ("replied", "referred") else "")
    who = cfgc.get("referral_contact") or "Referral desk"
    email = cfgc.get("referral_email")
    contact = (f'<a href="mailto:{e(email)}">{e(email)}</a>' if email
               else e(cfgc.get("method", "see site")))
    pinned = next((n for n in c["notes"] if n["pinned"]), None)
    pinned_html = (f'<div class="card-note" style="border-left:2px solid var(--pending);'
                   f'padding-left:8px;border-top:0">{e(pinned["body"])}</div>' if pinned else "")
    url = safe_url(cfgc.get("url"))
    variants = [("standard", "Introduction"), ("near_term", "Is there a puppy now")]
    return f"""<article class="card {tone}">
  <div class="card-top">
    <h3 class="card-name">{e(name)}</h3>
    <span class="card-meta">{e(cfgc.get("drive") or "")} · contact {e(_ago(c["last_contact"]))}</span>
  </div>
  <p class="card-body">{e(cfgc.get("territory") or "")}<br>{e(who)} — {contact}</p>
  {pinned_html}
  <div class="row">{stage_select("club", key, state["stage"])}
    <span class="card-meta">Checklist {done}/{applicable}</span></div>
  {entity_actions("club", key, state, variants, owner)}
  <details>
    <summary>Checklist and notes</summary>
    {checklist_block("club", key, c["items"], c["checks"])}
    {notes_block("club", key, c["notes"])}
  </details>
  {f'<div class="card-note"><a href="{e(url)}">{e(url)}</a></div>' if url else ""}
</article>"""


def finding_card(f):
    tone = "hot" if f["score"] >= 4 else ("warm" if f["kind"] == "nudge" else "cool")
    kind = {"litter": "Litter signal", "event": "Club event", "referral": "Referral page",
            "nudge": "Follow up", "ofa": "Clearances"}.get(f["kind"], f["kind"])
    url = safe_url(f.get("url"))
    link = f'<div class="card-note"><a href="{e(url)}">{e(url)}</a></div>' if url else ""
    return f"""<article class="card {tone}">
  <div class="card-top">
    <h3 class="card-name">{e(f["label"])}</h3>
    <span class="card-meta">{e(kind)} · {e(_ago(f["found_at"]))}</span>
  </div>
  <p class="card-body">{e(f["excerpt"])}</p>{link}
  <div class="row"><button class="ghost" data-dismiss="{f["id"]}">Done with this</button></div>
</article>"""


def log_block(events):
    if not events:
        return '<div class="empty">Nothing logged yet.</div>'
    rows = []
    for ev in events:
        when = datetime.fromtimestamp(ev["at"]).strftime("%d %b %H:%M")
        rows.append(f'<div class="log-row"><span class="log-when">{e(when)}</span>'
                    f'<span class="log-verb">{e(ev["verb"])}</span>'
                    f'<span>{e(ev["summary"])}</span></div>')
    return f'<div class="log">{"".join(rows)}</div>'


# ---------------------------------------------------------------- render

def render(cfg, data, user=None):
    is_owner = (user or {}).get("role", "owner") == "owner"
    owner = cfg.get("owner", {})
    urgent = [f for f in data["findings"]
              if f["kind"] in ("litter", "nudge") and f["score"] >= 2]
    ambient = [f for f in data["findings"] if f not in urgent][:10]

    urgent_html = ("".join(finding_card(f) for f in urgent[:12]) if urgent else
                   '<div class="empty">Nothing needs you right now.</div>')
    ambient_html = ("".join(finding_card(f) for f in ambient) if ambient else
                    '<div class="empty">No page changes recorded yet.</div>')
    breeders_html = ("".join(breeder_card(b, is_owner) for b in data["breeders"]) if data["breeders"]
                     else '<div class="empty">No breeders yet. They come from club '
                          'referral replies — add one below as soon as a name arrives.</div>')
    clubs_html = "".join(club_card(c, is_owner) for c in data["clubs"])

    unroutable = ""
    if data["unroutable"]:
        names = ", ".join(e(c["name"]) for c in data["unroutable"])
        unroutable = (f'<div class="empty"><b>{len(data["unroutable"])} clubs have no '
                      f'contact route on file.</b> They are not nagging you because there '
                      f'is nowhere to send anything — find a referral address and they '
                      f'rejoin the cadence.<br><br>{names}</div>')

    sweep_control = ("""<div class="row" style="margin-top:18px">\n  <button class="ghost" id="sweep">Sweep now</button>\n  <span class="card-meta">respects the polite crawl interval</span>\n</div>""" if is_owner else "")

    stamp = datetime.now().strftime("%d %b %Y, %H:%M")
    run = data["run"] or {}
    target = data["target"]
    target_txt = (f"aiming at {target.isoformat()}" if target
                  else "no live target date — both have passed")

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Golden Watch — {e(owner.get("name", ""))}</title>
<style>{CSS}</style></head><body><div class="wrap">

<header class="masthead">
  <h1 class="mast-title">Golden Watch</h1>
  <div class="mast-sub">
    <span>{e(owner.get("name", ""))} · {e(owner.get("base", ""))}</span>
    <span>{e(target_txt)}</span>
    <span>Last sweep {e(stamp)} · {e(run.get("checked", 0))} checked</span>
    <span>{e((user or {}).get("email", "local"))}</span>
  </div>
</header>
{scoreboard(data)}

<h2 class="eyebrow">Next 60 days <span class="count">{len(data["plan"])}</span></h2>
{plan_strip(data)}
<div class="row">
  <input type="date" id="plan-date">
  <input type="text" id="plan-what" placeholder="What is it — a clinic, a specialty, a call"
         style="flex:1;min-width:200px">
  <button id="plan-add">Add a date</button>
</div>

<h2 class="eyebrow">Needs you <span class="count">{len(urgent)}</span></h2>
{urgent_html}

<h2 class="eyebrow">Breeders <span class="count">{len(data["breeders"])}</span></h2>
<div class="grid">{breeders_html}</div>
<div class="row">
  <input type="text" id="nb-name" placeholder="Kennel name" style="flex:1;min-width:160px">
  <input type="text" id="nb-site" placeholder="https://…" style="flex:1;min-width:160px">
  <input type="text" id="nb-prov" placeholder="Referred by (e.g. Rose at CRVGRC)"
         style="flex:1;min-width:160px">
  <button id="nb-add">Add breeder</button>
</div>

<h2 class="eyebrow">Club referrals <span class="count">{len(data["clubs"])}</span></h2>
<div class="grid">{clubs_html}</div>
{unroutable}

<h2 class="eyebrow">Watch log <span class="count">{len(ambient)}</span></h2>
{ambient_html}

<h2 class="eyebrow">Activity <span class="count">{len(data["events"])}</span></h2>
{log_block(data["events"])}

{sweep_control}

<footer class="foot">
  Clearances are audited on the sire and dam of a specific breeding, not on a kennel.
  A prelim is not a clearance, and an eye exam expires in twelve months.
  Nothing here sends email.
</footer>
</div>
<div class="toast" id="toast"></div>
<script>{JS}</script>
</body></html>"""


JS = r"""
const toast = (msg) => {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  setTimeout(() => t.classList.remove('on'), 2200);
};

async function api(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-GW': '1'},
    body: JSON.stringify(body || {})
  });
  const data = await res.json().catch(() => ({error: 'bad response'}));
  if (!res.ok) { toast(data.error || 'failed'); throw new Error(data.error); }
  return data;
}

const d = (el, k) => el.dataset[k];

document.addEventListener('change', async (ev) => {
  const el = ev.target;
  if (el.matches('[data-stage]')) {
    await api('/api/stage', {kind: d(el,'kind'), key: d(el,'key'), stage: el.value});
    toast('Stage updated'); location.reload();
  }
  if (el.matches('[data-check]')) {
    await api('/api/checklist', {kind: d(el,'kind'), key: d(el,'key'),
                                 item: d(el,'item'), state: el.value});
    const row = el.closest('.check');
    row.className = 'check st-' + el.value;
    toast('Saved');
  }
  if (el.matches('[data-schedule]')) {
    await api('/api/schedule', {kind: d(el,'kind'), key: d(el,'key'), on_date: el.value});
    toast(el.value ? 'Will remind you on ' + el.value : 'Cleared');
  }
});

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('button');
  if (!el) return;

  if (el.matches('[data-rate]')) {
    await api('/api/rating', {kind: d(el,'kind'), key: d(el,'key'),
                              rating: parseInt(d(el,'rate'), 10)});
    location.reload();
  }

  if (el.matches('[data-dismiss]')) {
    await api('/api/dismiss', {id: parseInt(d(el,'dismiss'), 10)});
    el.closest('.card').remove(); toast('Cleared');
  }

  if (el.matches('[data-note-save]')) {
    const kind = d(el,'kind'), key = d(el,'key');
    const input = document.querySelector(
      `[data-note-input][data-kind="${kind}"][data-key="${key}"]`);
    if (!input.value.trim()) { toast('Nothing to save'); return; }
    await api('/api/note', {kind, key, body: input.value, pinned: d(el,'pin') ? 1 : 0});
    input.value = ''; toast('Noted'); location.reload();
  }

  if (el.matches('[data-draft]')) {
    const kind = d(el,'kind'), key = d(el,'key');
    const sel = document.querySelector(`[data-variant][data-key="${key}"]`);
    const box = document.querySelector(`[data-draftbox="${kind}:${key}"]`);
    const out = await api('/api/draft', {kind, key, variant: sel ? sel.value : 'standard'});
    box.textContent = '';
    const ta = document.createElement('textarea');
    ta.value = out.text;                    // value, never innerHTML
    box.appendChild(ta);
    if (out.blanks.length) {
      const w = document.createElement('div');
      w.className = 'warn';
      w.textContent = out.blanks.length + ' line(s) still have a blank to fill in — '
        + 'including the one specific true sentence about their dogs. '
        + 'Fill it before you send; it is the difference between a reply and the bin.';
      box.appendChild(w);
    }
    const row = document.createElement('div');
    row.className = 'row';
    const copy = document.createElement('button');
    copy.textContent = 'Copy';
    copy.onclick = async () => {
      await navigator.clipboard.writeText(ta.value);
      toast(out.blanks.length ? 'Copied — fill the blanks before sending' : 'Copied');
    };
    row.appendChild(copy);
    box.appendChild(row);
  }

  if (el.matches('[data-sent]')) {
    const summary = prompt('Anything to remember about what you sent?') ?? '';
    await api('/api/contact', {kind: d(el,'kind'), key: d(el,'key'),
                               direction: 'out', channel: 'email', summary});
    toast('Logged — clock reset'); location.reload();
  }

  if (el.matches('[data-reply]')) {
    const summary = prompt('What did they say?') ?? '';
    await api('/api/contact', {kind: d(el,'kind'), key: d(el,'key'),
                               direction: 'in', channel: 'email', summary});
    toast('Logged'); location.reload();
  }

  if (el.matches('[data-litter]')) {
    const due = prompt('Due or whelped date (YYYY-MM-DD), blank if unknown') ?? '';
    await api('/api/litter', {breeder_key: d(el,'key'), due_on: due, status: 'planned'});
    toast('Litter added'); location.reload();
  }

  if (el.id === 'plan-add') {
    const on_date = document.getElementById('plan-date').value;
    const what = document.getElementById('plan-what').value;
    if (!on_date || !what.trim()) { toast('Need a date and a description'); return; }
    await api('/api/commitment', {on_date, what});
    location.reload();
  }

  if (el.id === 'nb-add') {
    const name = document.getElementById('nb-name').value;
    if (!name.trim()) { toast('Need a name'); return; }
    await api('/api/breeder', {
      name,
      site: document.getElementById('nb-site').value,
      provenance: document.getElementById('nb-prov').value});
    toast('Added'); location.reload();
  }

  if (el.id === 'sweep') {
    await api('/api/sweep', {});
    toast('Sweep started — reload in a minute');
  }
});
"""

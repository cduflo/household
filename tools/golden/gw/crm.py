"""Reads and writes for the CRM tables.

Everything is keyed on the composite `(kind, key)`. Never call these with a bare
key: club keys and breeder keys share one namespace and nothing prevents a
collision, so a bare key would silently merge two entities' stage, notes and
checklist into one row.

Every mutation writes an `event`. That is the whole reliability story for the
log — if a write path forgets to log, the timeline silently lies, so the logging
lives here rather than in the callers.
"""
import json
import time

from . import model

#: One Supabase project hosts every household tool, so the shared tables carry
#: an `app` column. Golden's Python only ever handles golden, so it is a
#: constant here rather than a parameter threaded through forty call sites.
APP = "golden"


# ---------------------------------------------------------------- events

def log_event(con, verb, summary, kind="", key="", meta=None, actor=""):
    con.execute(
        "INSERT INTO event (app, at, kind, key, verb, summary, meta, actor)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (APP, time.time(), kind, key, verb, summary, json.dumps(meta or {}), actor),
    )


def events(con, kind=None, key=None, verb=None, limit=200):
    sql = "SELECT * FROM event WHERE app = %s"
    args = [APP]
    if kind:
        sql += " AND kind = %s"
        args.append(kind)
    if key:
        sql += " AND key = %s"
        args.append(key)
    if verb:
        sql += " AND verb = %s"
        args.append(verb)
    sql += " ORDER BY at DESC LIMIT %s"
    args.append(limit)
    return [r for r in con.execute(sql, args)]


# ---------------------------------------------------------------- state

def get_state(con, kind, key):
    row = con.execute(
        "SELECT * FROM entity_state WHERE app = %s AND kind = %s AND key = %s",
        (APP, kind, key)
    ).fetchone()
    return row


def ensure_state(con, kind, key, stage=None):
    """Create the row if absent. Idempotent, so it is safe to call on render."""
    existing = get_state(con, kind, key)
    if existing:
        return existing
    con.execute(
        "INSERT INTO entity_state (app, kind, key, stage, updated_at)"
        " VALUES (%s,%s,%s,%s,%s)",
        (APP, kind, key, stage or model.initial_stage(kind), time.time()),
    )
    return get_state(con, kind, key)


def all_states(con):
    return {(r["kind"], r["key"]): r
            for r in con.execute("SELECT * FROM entity_state WHERE app = %s", (APP,))}


#: config.yaml's original five-value `status:` vocabulary, mapped onto the
#: stages. Seeding only -- see `sync_entities`.
LEGACY_STATUS = {"researching": "new", "contacted": "contacted", "replied": "talking",
                 "waitlist": "waitlist", "passed": "out"}


def sync_entities(con, cfg):
    """Give every club and breeder in config a state row.

    Config stays the declarative half -- who exists, their address, their
    territory. The database owns everything that changes because time passed or
    you clicked something. A breeder's config `status:` is read exactly once, to
    seed the stage; after that the database is authoritative and config is
    ignored, because two writers for one fact is how they silently diverge.
    """
    for i, club in enumerate(cfg.get("clubs", [])):
        if club.get("method") == "reference":
            continue
        ensure_state(con, "club", club["key"])
        publish_entity(con, "club", club["key"], club.get("name", club["key"]),
                       subtitle=club.get("territory", ""),
                       detail=" · ".join(x for x in (club.get("drive"),
                                                     club.get("referral_contact")) if x),
                       url=club.get("url", ""), email=club.get("referral_email", ""),
                       sort=i)
    for i, b in enumerate(cfg.get("breeders", [])):
        ensure_state(con, "breeder", b["key"],
                     stage=LEGACY_STATUS.get(b.get("status"), "new"))
        line = (b.get("line") or "unknown").lower()
        publish_entity(con, "breeder", b["key"], b.get("name", b["key"]),
                       subtitle=b.get("location", ""),
                       detail={"show": "Show lines", "field": "Field lines",
                               "dual": "Dual purpose"}.get(line, "Line unknown"),
                       url=b.get("site", ""), email=b.get("email", ""), sort=i)


def publish_entity(con, kind, key, name, subtitle="", detail="", url="", email="", sort=0):
    """Copy config identity into Postgres for the browser to render.

    Config is the source of truth for rows it owns: these are rewritten on
    every sweep, so if a name is wrong here, config.yaml is wrong.

    Rows captured from the board carry source='ui' and are left alone. That
    matters because the highest-value moment in the search is a referral reply
    arriving with three kennel names -- you want those on the board from a
    phone in twenty seconds, and a sweep an hour later must not erase them.
    """
    con.execute(
        """INSERT INTO entity (app, kind, key, name, subtitle, detail, url, email,
                               sort, source, watched, at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'config',1,%s)
           ON CONFLICT (app, kind, key) DO UPDATE SET
             name=excluded.name, subtitle=excluded.subtitle, detail=excluded.detail,
             url=excluded.url, email=excluded.email, sort=excluded.sort,
             source='config', watched=1, at=excluded.at
           WHERE entity.source = 'config'""",
        (APP, kind, key, name, subtitle, detail, url, email, sort, time.time()))


def set_stage(con, kind, key, stage, label=None):
    if stage not in model.stages_for(kind):
        raise ValueError(f"{stage!r} is not a {kind} stage")
    before = ensure_state(con, kind, key)["stage"]
    con.execute(
        "UPDATE entity_state SET stage = %s, updated_at = %s"
        " WHERE app = %s AND kind = %s AND key = %s",
        (stage, time.time(), APP, kind, key),
    )
    log_event(con, "stage", f"{label or key}: {model.STAGE_LABELS.get(before, before)}"
                            f" → {model.STAGE_LABELS.get(stage, stage)}",
              kind, key, {"from": before, "to": stage})
    return stage


def set_rating(con, kind, key, rating, label=None):
    value = model.clamp_rating(rating)
    ensure_state(con, kind, key)
    con.execute(
        "UPDATE entity_state SET rating = %s, updated_at = %s"
        " WHERE app = %s AND kind = %s AND key = %s",
        (value, time.time(), APP, kind, key),
    )
    log_event(con, "rating", f"{label or key}: rated {value}/5 — "
                             f"{model.RATING_LABELS[value]}", kind, key, {"rating": value})
    return value


def set_ball(con, kind, key, ball, label=None):
    """Whose turn it is.

    "They asked me a question three days ago" is a five-alarm state that a
    last-contacted timestamp renders as "recently contacted, all good".
    """
    if ball not in ("", "us", "them"):
        raise ValueError("ball must be '', 'us' or 'them'")
    ensure_state(con, kind, key)
    con.execute(
        "UPDATE entity_state SET ball = %s, updated_at = %s"
        " WHERE app = %s AND kind = %s AND key = %s",
        (ball, time.time(), APP, kind, key),
    )
    log_event(con, "ball", f"{label or key}: ball with {ball or 'nobody'}", kind, key)
    return ball


def set_next_contact(con, kind, key, on_date, label=None):
    """An explicit date beats every interval.

    A breeder who says "check back after Tessa's next season, around October"
    has told you the cadence. A 30-day timer firing at them in the meantime is
    goodwill burn.
    """
    ensure_state(con, kind, key)
    con.execute(
        "UPDATE entity_state SET next_contact_on = %s, updated_at = %s"
        " WHERE app = %s AND kind = %s AND key = %s",
        (on_date or "", time.time(), APP, kind, key),
    )
    log_event(con, "schedule",
              f"{label or key}: next contact {on_date or 'cleared'}", kind, key)
    return on_date


# ---------------------------------------------------------------- notes

def add_note(con, kind, key, body, pinned=0, label=None, author=""):
    body = (body or "").strip()
    if not body:
        raise ValueError("empty note")
    row = con.execute(
        "INSERT INTO note (app, kind, key, body, pinned, at, author)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (APP, kind, key, body, 1 if pinned else 0, time.time(), author),
    ).fetchone()
    log_event(con, "note", f"{label or key}: {body[:80]}", kind, key, actor=author)
    return row["id"]


def edit_note(con, note_id, body):
    """Editable forever, with the prior text preserved in the event log.

    A fifteen-minute freeze window was considered and dropped: the realistic
    failure is writing "September, out of Tessa" from memory and finding the
    email three days later saying August, out of Bessie. Blocking that edit
    leaves a wrong pinned fact on the card and a right correction underneath it.
    """
    row = con.execute("SELECT * FROM note WHERE id = %s", (note_id,)).fetchone()
    if not row:
        return None
    con.execute("UPDATE note SET body = %s WHERE id = %s", ((body or "").strip(), note_id))
    log_event(con, "note_edit", f"edited: {body[:60]}", row["kind"], row["key"],
              {"was": row["body"]})
    return note_id


def set_note_pinned(con, note_id, pinned):
    con.execute("UPDATE note SET pinned = %s WHERE id = %s", (1 if pinned else 0, note_id))
    return note_id


def notes(con, kind, key):
    return [r for r in con.execute(
        "SELECT * FROM note WHERE app = %s AND kind = %s AND key = %s"
        " ORDER BY pinned DESC, at DESC", (APP, kind, key))]


def all_notes(con):
    out = {}
    for r in con.execute("SELECT * FROM note WHERE app = %s"
                         " ORDER BY pinned DESC, at DESC", (APP,)):
        out.setdefault((r["kind"], r["key"]), []).append(r)
    return out


# ---------------------------------------------------------------- checklist

def set_item(con, kind, key, item, state, note="", label=None):
    if state not in model.ITEM_STATES:
        raise ValueError(f"{state!r} is not a checklist state")
    con.execute(
        """INSERT INTO checklist (kind, key, item, state, note, at) VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT(kind, key, item) DO UPDATE SET
             state = excluded.state, note = excluded.note, at = excluded.at""",
        (kind, key, item, state, note or "", time.time()),
    )
    log_event(con, "checklist", f"{label or key}: {item} → {state}", kind, key,
              {"item": item, "state": state})
    return state


def checklist(con, kind, key):
    return {r["item"]: r["state"] for r in con.execute(
        "SELECT item, state FROM checklist WHERE kind = %s AND key = %s", (kind, key))}


def checklist_notes(con, kind, key):
    return {r["item"]: r["note"] for r in con.execute(
        "SELECT item, note FROM checklist WHERE kind = %s AND key = %s", (kind, key))}


def all_checklists(con):
    out = {}
    for r in con.execute("SELECT kind, key, item, state FROM checklist"):
        out.setdefault((r["kind"], r["key"]), {})[r["item"]] = r["state"]
    return out


# ---------------------------------------------------------------- commitments

def add_commitment(con, on_date, what, kind="", key="", note=""):
    if not model.parse_iso(on_date):
        raise ValueError("commitment needs an ISO date")
    row = con.execute(
        "INSERT INTO commitment (app, on_date, what, kind, key, note, at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (APP, on_date, what, kind, key, note, time.time()),
    ).fetchone()
    log_event(con, "commitment", f"{on_date}: {what}", kind, key)
    return row["id"]


def commitments(con, include_done=False):
    sql = "SELECT * FROM commitment WHERE app = %s"
    if not include_done:
        sql += " AND done = 0"
    return [r for r in con.execute(sql + " ORDER BY on_date", (APP,))]


def complete_commitment(con, commitment_id, done=1):
    con.execute("UPDATE commitment SET done = %s WHERE id = %s", (1 if done else 0, commitment_id))
    row = con.execute("SELECT * FROM commitment WHERE id = %s", (commitment_id,)).fetchone()
    if row:
        log_event(con, "commitment", f"{'did' if done else 'reopened'}: {row['what']}",
                  row["kind"], row["key"])
    return commitment_id


# ---------------------------------------------------------------- dogs

DOG_FIELDS = ("registered_name", "call_name", "sex", "dob", "breeder_key", "chic",
              "hips", "hips_date", "elbows", "elbows_date", "eyes_date",
              "heart", "heart_date", "dna", "note")


def add_dog(con, **fields):
    data = {k: fields.get(k) or "" for k in DOG_FIELDS}
    if not data["registered_name"]:
        raise ValueError("a dog needs a registered name")
    if isinstance(fields.get("dna"), dict):
        data["dna"] = json.dumps(fields["dna"])
    data["dna"] = data["dna"] or "{}"
    cols = ", ".join(DOG_FIELDS)
    marks = ", ".join("%s" for _ in DOG_FIELDS)
    row = con.execute(
        f"INSERT INTO dog ({cols}, updated_at) VALUES ({marks}, %s) RETURNING id",
        tuple(data[k] for k in DOG_FIELDS) + (time.time(),),
    ).fetchone()
    log_event(con, "dog", f"added {data['registered_name']}",
              "breeder", data["breeder_key"], {"dog_id": row["id"]})
    return row["id"]


def update_dog(con, dog_id, **fields):
    sets, args = [], []
    for k in DOG_FIELDS:
        if k in fields:
            value = fields[k]
            if k == "dna" and isinstance(value, dict):
                value = json.dumps(value)
            sets.append(f"{k} = %s")
            args.append(value if value is not None else "")
    if not sets:
        return dog_id
    args += [time.time(), dog_id]
    con.execute(f"UPDATE dog SET {', '.join(sets)}, updated_at = %s WHERE id = %s", args)
    row = get_dog(con, dog_id)
    log_event(con, "dog", f"updated {row['registered_name'] if row else dog_id}",
              "breeder", (row or {}).get("breeder_key", ""), {"dog_id": dog_id})
    return dog_id


def get_dog(con, dog_id):
    if not dog_id:
        return None
    row = con.execute("SELECT * FROM dog WHERE id = %s", (dog_id,)).fetchone()
    return row


def dogs(con):
    return [r for r in con.execute("SELECT * FROM dog ORDER BY registered_name")]


# ---------------------------------------------------------------- litters

LITTER_STATUSES = ["planned", "bred", "confirmed", "whelped", "placed", "passed"]


def add_litter(con, breeder_key, **fields):
    row = con.execute(
        """INSERT INTO litter (breeder_key, sire_id, dam_id, status, bred_on, due_on,
                               whelped_on, pups_total, pups_female, pick_number, note,
                               updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (breeder_key, fields.get("sire_id"), fields.get("dam_id"),
         fields.get("status") or "planned", fields.get("bred_on") or "",
         fields.get("due_on") or "", fields.get("whelped_on") or "",
         fields.get("pups_total"), fields.get("pups_female"),
         fields.get("pick_number"), fields.get("note") or "", time.time()),
    ).fetchone()
    log_event(con, "litter", f"litter added ({fields.get('status') or 'planned'})",
              "breeder", breeder_key, {"litter_id": row["id"]})
    return row["id"]


def update_litter(con, litter_id, **fields):
    allowed = ("sire_id", "dam_id", "status", "bred_on", "due_on", "whelped_on",
               "pups_total", "pups_female", "pick_number", "note")
    sets, args = [], []
    for k in allowed:
        if k in fields:
            sets.append(f"{k} = %s")
            args.append(fields[k])
    if not sets:
        return litter_id
    args += [time.time(), litter_id]
    con.execute(f"UPDATE litter SET {', '.join(sets)}, updated_at = %s WHERE id = %s", args)
    row = con.execute("SELECT * FROM litter WHERE id = %s", (litter_id,)).fetchone()
    log_event(con, "litter", f"litter updated ({fields.get('status', 'edited')})",
              "breeder", row["breeder_key"] if row else "", {"litter_id": litter_id})
    return litter_id


def litters(con, breeder_key=None):
    sql = "SELECT * FROM litter"
    args = ()
    if breeder_key:
        sql += " WHERE breeder_key = %s"
        args = (breeder_key,)
    return [r for r in con.execute(sql + " ORDER BY COALESCE(NULLIF(due_on,''), whelped_on, bred_on) DESC", args)]


def litter_audit(con, litter, asof=None):
    """The clearance verdict for an actual pairing — the only level at which
    the question means anything."""
    return model.audit_pairing(get_dog(con, litter.get("sire_id")),
                               get_dog(con, litter.get("dam_id")), asof)


def best_litter_audit(con, breeder_key, asof=None):
    """The strongest pairing on file for a breeder, for the summary card.

    Deliberately not an average across litters: you are choosing one puppy from
    one breeding, so the question is whether *a* good pairing exists, not
    whether the kennel's mean is respectable.
    """
    best = None
    for lit in litters(con, breeder_key):
        audit = litter_audit(con, lit, asof)
        if best is None or audit["score"] > best[1]["score"]:
            best = (lit, audit)
    return best
